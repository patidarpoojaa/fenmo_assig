from __future__ import annotations

import os
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import pandas as pd
import requests
import streamlit as st

from backend.embedded import ensure_embedded_api


API_UNAVAILABLE_MESSAGE = (
    "The expense API is not reachable. If you are running locally, start it with "
    "`python -m uvicorn backend.main:app --reload` or use `start_app.bat`, "
    "then refresh this page."
)


def get_api_base_url() -> str:
    configured_url = os.getenv("EXPENSE_API_URL", "").strip()
    if not configured_url:
        try:
            configured_url = st.secrets.get("EXPENSE_API_URL")
        except Exception:
            configured_url = None

    if not configured_url:
        return ensure_embedded_api()

    api_url = configured_url
    if not api_url.startswith(("http://", "https://")):
        api_url = f"http://{api_url}"
    return api_url.rstrip("/")


API_BASE_URL = ""
DISPLAY_TIMEZONE = timezone(timedelta(hours=5, minutes=30), "IST")


def format_currency(value: Decimal) -> str:
    return f"₹{value:,.2f}"


def parse_money(value: object) -> Decimal:
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def format_created_at(value: object) -> str:
    try:
        created_at = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    return created_at.astimezone(DISPLAY_TIMEZONE).strftime("%d %b %Y, %I:%M %p IST")


def fetch_expenses(category: str | None = None, sort_desc: bool = False) -> list[dict]:
    params: dict[str, str] = {}
    if category:
        params["category"] = category
    if sort_desc:
        params["sort"] = "date_desc"

    response = requests.get(f"{API_BASE_URL}/expenses", params=params, timeout=10)
    response.raise_for_status()
    return response.json()


def create_expense(payload: dict, idempotency_key: str) -> requests.Response:
    return requests.post(
        f"{API_BASE_URL}/expenses",
        json=payload,
        headers={"Idempotency-Key": idempotency_key},
        timeout=10,
    )


def ensure_submission_key() -> str:
    if "draft_idempotency_key" not in st.session_state:
        st.session_state.draft_idempotency_key = str(uuid.uuid4())
    return st.session_state.draft_idempotency_key


st.set_page_config(page_title="Expense Tracker", page_icon="₹", layout="wide")
try:
    API_BASE_URL = get_api_base_url()
except RuntimeError as exc:
    st.error(f"Could not start the internal expense API. Details: {exc}")
    st.stop()

st.markdown(
    """
    <style>
    [data-testid="stHeaderActionElements"] {
        display: none;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


st.markdown(
    "<h1 style='text-align: center;'>Expense Tracker</h1>",
    unsafe_allow_html=True,
)

st.header("Add expense")

with st.form("expense-form", clear_on_submit=False):
    cols = st.columns([1, 1, 1, 2])
    amount = cols[0].number_input(
        "Amount",
        min_value=0.0,
        step=10.0,
        format="%.2f",
    )
    category = cols[1].text_input("Category", placeholder="Food")
    expense_date = cols[2].date_input("Date", value=date.today())
    description = cols[3].text_input("Description", placeholder="Lunch")
    submitted = st.form_submit_button("Add expense", type="primary")

if submitted:
    payload = {
        "amount": f"{amount:.2f}",
        "category": category.strip(),
        "description": description.strip(),
        "date": expense_date.isoformat(),
    }

    if amount <= 0:
        st.error("Amount must be greater than zero.")
    elif not payload["category"]:
        st.error("Category is required.")
    else:
        try:
            with st.spinner("Saving expense..."):
                result = create_expense(payload, ensure_submission_key())
            if result.status_code in (200, 201):
                st.session_state.last_saved_message = "Expense saved."
                st.session_state.draft_idempotency_key = str(uuid.uuid4())
                st.rerun()
            else:
                st.error(result.json().get("detail", "Could not save the expense."))
        except requests.RequestException as exc:
            st.error(f"{API_UNAVAILABLE_MESSAGE} Details: {exc}")

if st.session_state.get("last_saved_message"):
    st.success(st.session_state.pop("last_saved_message"))

st.header("Expenses")

try:
    with st.spinner("Loading expenses..."):
        all_expenses = fetch_expenses()
except requests.RequestException as exc:
    st.error(f"{API_UNAVAILABLE_MESSAGE} Details: {exc}")
    st.stop()

categories = sorted({expense["category"] for expense in all_expenses})
controls = st.columns([2, 1], vertical_alignment="bottom")
category_choice = controls[0].selectbox("Filter by category", ["All", *categories])
sort_desc = controls[1].toggle("Newest date first", value=True)

selected_category = None if category_choice == "All" else category_choice

try:
    with st.spinner("Refreshing list..."):
        visible_expenses = fetch_expenses(category=selected_category, sort_desc=sort_desc)
except requests.RequestException as exc:
    st.error(f"{API_UNAVAILABLE_MESSAGE} Details: {exc}")
    st.stop()

total = sum((parse_money(expense["amount"]) for expense in visible_expenses), Decimal("0.00"))
st.metric("Total", format_currency(total))

if not visible_expenses:
    st.info("No expenses match the current view.")
else:
    table_rows = [
        {
            "Date": expense["date"],
            "Category": expense["category"],
            "Description": expense["description"],
            "Amount": format_currency(parse_money(expense["amount"])),
            "Created at": format_created_at(expense["created_at"]),
        }
        for expense in visible_expenses
    ]
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    summary_rows = {}
    for expense in visible_expenses:
        summary_rows.setdefault(expense["category"], Decimal("0.00"))
        summary_rows[expense["category"]] += parse_money(expense["amount"])

    st.subheader("Categorical Expenses")
    st.dataframe(
        pd.DataFrame(
            [
                {"Category": category, "Total": format_currency(amount)}
                for category, amount in sorted(summary_rows.items())
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
