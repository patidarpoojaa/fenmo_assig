from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from backend.main import create_app


TEST_DB_DIR = Path(__file__).resolve().parents[1] / "test-data"


def make_client(test_name: str) -> TestClient:
    TEST_DB_DIR.mkdir(exist_ok=True)
    db_path = TEST_DB_DIR / f"{test_name}.db"
    for path in [db_path, db_path.with_suffix(".db-shm"), db_path.with_suffix(".db-wal")]:
        if path.exists():
            path.unlink()

    app = create_app(db_path)
    return TestClient(app)


def test_create_and_list_expense() -> None:
    with make_client("create-and-list") as client:
        response = client.post(
            "/expenses",
            json={
                "amount": "125.50",
                "category": "Food",
                "description": "Lunch",
                "date": "2026-04-29",
            },
            headers={"Idempotency-Key": "create-food-1"},
        )

        assert response.status_code == 201
        created = response.json()
        assert created["amount"] == "125.50"
        assert created["category"] == "Food"

        list_response = client.get("/expenses")
        assert list_response.status_code == 200
        expenses = list_response.json()
        assert len(expenses) == 1
        assert expenses[0]["id"] == created["id"]


def test_idempotent_retry_returns_existing_expense() -> None:
    payload = {
        "amount": "999.99",
        "category": "Travel",
        "description": "Train",
        "date": "2026-04-28",
    }

    with make_client("idempotent-retry") as client:
        first = client.post(
            "/expenses",
            json=payload,
            headers={"Idempotency-Key": "retry-safe-key"},
        )
        retry = client.post(
            "/expenses",
            json=payload,
            headers={"Idempotency-Key": "retry-safe-key"},
        )

        assert first.status_code == 201
        assert retry.status_code == 200
        assert retry.json()["id"] == first.json()["id"]
        assert len(client.get("/expenses").json()) == 1


def test_reusing_key_with_different_payload_is_rejected() -> None:
    with make_client("key-conflict") as client:
        first = client.post(
            "/expenses",
            json={
                "amount": "25.00",
                "category": "Food",
                "description": "Tea",
                "date": "2026-04-29",
            },
            headers={"Idempotency-Key": "same-key"},
        )
        second = client.post(
            "/expenses",
            json={
                "amount": "30.00",
                "category": "Food",
                "description": "Tea",
                "date": "2026-04-29",
            },
            headers={"Idempotency-Key": "same-key"},
        )

        assert first.status_code == 201
        assert second.status_code == 409


def test_filter_and_sort_by_date_desc() -> None:
    with make_client("filter-sort") as client:
        client.post(
            "/expenses",
            json={
                "amount": "10.00",
                "category": "Food",
                "description": "Older",
                "date": "2026-04-01",
            },
        )
        client.post(
            "/expenses",
            json={
                "amount": "20.00",
                "category": "Bills",
                "description": "Internet",
                "date": "2026-04-20",
            },
        )
        client.post(
            "/expenses",
            json={
                "amount": "30.00",
                "category": "Food",
                "description": "Newer",
                "date": "2026-04-29",
            },
        )

        response = client.get("/expenses", params={"category": "Food", "sort": "date_desc"})

        assert response.status_code == 200
        expenses = response.json()
        assert [expense["description"] for expense in expenses] == ["Newer", "Older"]


def test_rejects_invalid_amount() -> None:
    with make_client("invalid-amount") as client:
        response = client.post(
            "/expenses",
            json={
                "amount": "-1.00",
                "category": "Food",
                "description": "Invalid",
                "date": "2026-04-29",
            },
        )

        assert response.status_code == 422
