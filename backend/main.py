from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Header, HTTPException, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator


CENTS = Decimal("0.01")
PAISE_PER_RUPEE = Decimal("100")


def default_database_path() -> Path:
    configured = os.getenv("EXPENSE_TRACKER_DB")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "data" / "expenses.db"


def get_connection(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db(db_path: Path) -> None:
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
                category TEXT NOT NULL CHECK (length(trim(category)) > 0),
                description TEXT NOT NULL,
                date TEXT NOT NULL,
                created_at TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                request_hash TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_expenses_category ON expenses(category)"
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_expenses_date ON expenses(date)")


class ExpenseCreate(BaseModel):
    amount: Decimal = Field(..., description="Positive rupee amount with up to 2 decimals")
    category: str = Field(..., min_length=1, max_length=64)
    description: str = Field("", max_length=280)
    date: date

    @field_validator("amount", mode="before")
    @classmethod
    def parse_amount(cls, value: object) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, ValueError):
            raise ValueError("Amount must be a valid number") from None

        if not amount.is_finite():
            raise ValueError("Amount must be finite")
        if amount <= 0:
            raise ValueError("Amount must be greater than zero")
        if amount.as_tuple().exponent < -2:
            raise ValueError("Amount must have at most 2 decimal places")

        return amount.quantize(CENTS)

    @field_validator("category", "description", mode="before")
    @classmethod
    def trim_text(cls, value: object) -> str:
        if value is None:
            return ""
        return str(value).strip()


class ExpenseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    amount: str
    category: str
    description: str
    date: date
    created_at: datetime


def amount_to_minor(amount: Decimal) -> int:
    return int(amount * PAISE_PER_RUPEE)


def minor_to_amount(amount_minor: int) -> str:
    return f"{Decimal(amount_minor) / PAISE_PER_RUPEE:.2f}"


def canonical_request_hash(expense: ExpenseCreate) -> str:
    payload = {
        "amount_minor": amount_to_minor(expense.amount),
        "category": expense.category,
        "description": expense.description,
        "date": expense.date.isoformat(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def row_to_expense(row: sqlite3.Row) -> dict[str, object]:
    return {
        "id": row["id"],
        "amount": minor_to_amount(row["amount_minor"]),
        "category": row["category"],
        "description": row["description"],
        "date": row["date"],
        "created_at": row["created_at"],
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def fetch_by_idempotency_key(
    conn: sqlite3.Connection, idempotency_key: str
) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM expenses WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()


def create_app(db_path: str | Path | None = None) -> FastAPI:
    resolved_db_path = Path(db_path) if db_path is not None else default_database_path()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        init_db(resolved_db_path)
        yield

    app = FastAPI(
        title="Expense Tracker API",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.post(
        "/expenses",
        response_model=ExpenseRead,
        status_code=status.HTTP_201_CREATED,
        summary="Create a new expense",
    )
    def create_expense(
        payload: ExpenseCreate,
        response: Response,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict[str, object]:
        amount_minor = amount_to_minor(payload.amount)
        request_hash = canonical_request_hash(payload) if idempotency_key else None
        created_at = utc_now_iso()

        with get_connection(resolved_db_path) as conn:
            if idempotency_key:
                existing = fetch_by_idempotency_key(conn, idempotency_key)
                if existing is not None:
                    if existing["request_hash"] != request_hash:
                        raise HTTPException(
                            status_code=status.HTTP_409_CONFLICT,
                            detail="Idempotency-Key was already used with a different payload",
                        )
                    response.status_code = status.HTTP_200_OK
                    return row_to_expense(existing)

            try:
                cursor = conn.execute(
                    """
                    INSERT INTO expenses (
                        amount_minor, category, description, date, created_at,
                        idempotency_key, request_hash
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        amount_minor,
                        payload.category,
                        payload.description,
                        payload.date.isoformat(),
                        created_at,
                        idempotency_key,
                        request_hash,
                    ),
                )
            except sqlite3.IntegrityError:
                if not idempotency_key:
                    raise

                existing = fetch_by_idempotency_key(conn, idempotency_key)
                if existing is None or existing["request_hash"] != request_hash:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Idempotency-Key was already used with a different payload",
                    ) from None

                response.status_code = status.HTTP_200_OK
                return row_to_expense(existing)

            created = conn.execute(
                "SELECT * FROM expenses WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()

        return row_to_expense(created)

    @app.get(
        "/expenses",
        response_model=list[ExpenseRead],
        summary="List expenses with optional filtering and sorting",
    )
    def list_expenses(
        category: Annotated[str | None, Query(max_length=64)] = None,
        sort: Annotated[str | None, Query(pattern="^date_desc$")] = None,
    ) -> list[dict[str, object]]:
        where = ""
        params: list[object] = []

        if category and category.strip():
            where = "WHERE category = ?"
            params.append(category.strip())

        order_by = "ORDER BY created_at DESC, id DESC"
        if sort == "date_desc":
            order_by = "ORDER BY date DESC, created_at DESC, id DESC"

        with get_connection(resolved_db_path) as conn:
            rows = conn.execute(
                f"SELECT * FROM expenses {where} {order_by}",
                params,
            ).fetchall()

        return [row_to_expense(row) for row in rows]

    @app.get("/health", summary="Health check")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", summary="API information")
    def root() -> dict[str, str]:
        return {
            "name": "Expense Tracker API",
            "docs": "/docs",
            "health": "/health",
        }

    return app


app = create_app()
