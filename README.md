# Expense Tracker

A minimal full-stack personal finance tool built for the assignment brief:

- FastAPI backend API
- Streamlit frontend
- SQLite persistence
- Idempotent expense creation for safe client retries
- Basic validation, loading/error UI states, and a small test suite

## Run locally

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the API:

```bash
uvicorn backend.main:app --reload
```

In another terminal, start the Streamlit app:

```bash
streamlit run streamlit_app.py
```

On Windows, you can also double-click `start_app.bat` to start both the API and Streamlit app. If you only run `streamlit run streamlit_app.py`, the frontend starts an internal FastAPI server automatically so it can still work on Streamlit Community Cloud.

By default, the frontend talks to `http://127.0.0.1:8000`.

The SQLite database is created at `data/expenses.db`.

## API

### `POST /expenses`

Creates an expense.

```json
{
  "amount": "125.50",
  "category": "Food",
  "description": "Lunch",
  "date": "2026-04-29"
}
```

Use an `Idempotency-Key` header for retry safety. If the same key and same payload are submitted again, the API returns the original expense instead of creating a duplicate. If the same key is reused with a different payload, the API returns `409 Conflict`.

### `GET /expenses`

Returns expenses. Optional query parameters:

- `category=Food`
- `sort=date_desc`

## Tests

```bash
pytest
```

The tests cover expense creation, list retrieval, category filtering, date sorting, amount validation, and idempotent retry behavior.

## Design decisions

SQLite is used because it is durable, simple to run locally, and a better fit for realistic refresh/retry behavior than an in-memory store. Money is stored as integer paise (`amount_minor`) to avoid floating point rounding errors, while API responses expose a two-decimal rupee amount string.

The backend supports optional `Idempotency-Key` headers. Without a key, `POST /expenses` behaves like a normal create endpoint. With a key, it becomes safe for the Streamlit app to retry after a slow response, failed response, double submit, or browser refresh.

## Trade-offs

Authentication, user accounts, recurring expenses, pagination, and deployment configuration are intentionally left out to keep the feature set focused. The frontend uses simple Streamlit components rather than a custom design system. Category filtering is exact-match based on the existing saved categories.

## Streamlit Community Cloud deployment

The app is deployed on Streamlit Community Cloud:

https://expense-tracker-fenma-assignment.streamlit.app/

## Intentionally not done

Custom design system: used simple Streamlit components because of the timebox.
User authentication and multi-user support were intentionally not included
to keep the system focused and maintainable within the time constraint.
