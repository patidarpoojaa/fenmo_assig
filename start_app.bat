@echo off
setlocal
cd /d "%~dp0"
set EXPENSE_API_URL=http://127.0.0.1:8000

start "Expense Tracker API" cmd /k python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000
timeout /t 3 /nobreak >nul
start "Expense Tracker Streamlit" cmd /k python -m streamlit run streamlit_app.py

echo Expense Tracker is starting.
echo Open http://127.0.0.1:8501 in your browser.
echo API docs are at http://127.0.0.1:8000/docs.
