# Homestead backend

A small FastAPI service that stores the construction budget and serves `../index.html`.

## Run locally

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env   # then edit the values
$env:DATABASE_URL="sqlite:///./homestead.db"; $env:APP_USERNAME="you"; $env:APP_PASSWORD="your-password"; $env:SESSION_SECRET="long-random-string"; $env:COOKIE_SECURE="false"
.\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

Open http://127.0.0.1:8000/. Set `COOKIE_SECURE=false` only for plain-http local testing.

## Run tests

```powershell
.\.venv\Scripts\python -m pip install pytest httpx
.\.venv\Scripts\python -m pytest -q tests
```

## Deploy (free tier)

1. Create a free PostgreSQL database on [Neon](https://neon.tech) and copy its connection string (keep `?sslmode=require`).
2. Push the repository to GitHub, then on Render choose **New > Blueprint** and select the repo. The root `render.yaml` sets the root directory (`backend`), build command, start command, and Python version.
3. Enter the secret values Render asks for in its dashboard: `DATABASE_URL` (the Neon URL), `APP_USERNAME`, and `APP_PASSWORD`. `SESSION_SECRET` is generated automatically. Never commit these values.

The app serves `index.html` and `expenses.html` from the repository root, so keep the whole repo deployed, not only `backend/`.

Tables are created automatically on startup.

## API

| Method | Path | Auth | Purpose |
| --- | --- | --- | --- |
| POST | `/api/login` | No | Body `{username, password}`; sets a session cookie |
| POST | `/api/logout` | No | Clears the session cookie |
| GET | `/api/me` | Yes | Returns 200 if logged in |
| GET | `/api/budget` | Yes | Current figures (404 if none saved yet) |
| PUT | `/api/budget` | Yes | Body `{budget_paise, paid_paise}`; saves and records history |
| GET | `/api/budget/history?limit=50` | Yes | Past saved values, newest first |
| GET | `/api/expenses` | Yes | All expenses, newest first |
| POST | `/api/expenses` | Yes | Add an expense; its amount is added to amount paid |
| PUT | `/api/expenses/{id}` | Yes | Edit an expense; amount paid changes by the difference |
| DELETE | `/api/expenses/{id}` | Yes | Delete an expense; its amount is removed from amount paid |

Amounts are integers in paise (1 rupee = 100 paise).
