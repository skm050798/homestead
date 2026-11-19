# Homestead backend

A small FastAPI service that stores the construction budget and serves `../index.html`.

## Run locally

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env   # then edit the values
.\.venv\Scripts\python -m uvicorn app.main:app --env-file .env --port 8000
```

Before starting, set your login and a random `SESSION_SECRET` in `.env`, and set
`COOKIE_SECURE=false` for local HTTP only. Keep the server running and open
http://127.0.0.1:8000/. If a tab says **Failed to fetch** after a local server
stops, start the server again and reopen the app at the address Uvicorn prints.

## Run tests

```powershell
.\.venv\Scripts\python -m pip install pytest httpx
.\.venv\Scripts\python -m pytest -q tests
```

## Deploy (free tier)

1. Create a free PostgreSQL database on [Neon](https://neon.tech) and copy its connection string (keep `?sslmode=require`).
2. Push the repository to GitHub, then on Render choose **New > Blueprint** and select the repo. The root `render.yaml` sets the root directory (`backend`), build command, start command, and Python version.
3. Enter the secret values Render asks for in its dashboard: `DATABASE_URL` (the Neon URL), `APP_USERNAME`, and `APP_PASSWORD`. `SESSION_SECRET` is generated automatically. Never commit these values.

The app serves `index.html`, `expenses.html`, and `payment-schedule.html` from the repository root, so keep the whole repo deployed, not only `backend/`.

Tables are created automatically on startup.

## Import a payment schedule

Open [**Payment schedule**](http://127.0.0.1:8000/payment-schedule.html) from the dashboard or Expenses page, choose a PDF, and select **Import PDF**.
The PDF must be unlocked, at most 5 MB and 20 pages, and contain a selectable-text
table with an `Amount` column and either a `Milestone` or `Description` column.
Keep each payment on one line. The importer ignores other columns, calculates
each payment's share of the imported total, and sets every status to `Pending`.
Image-only scans are not supported; export the original table as a text PDF or
run OCR first.

Use **Mark paid** or **Mark pending** beside a milestone. These changes are saved
to the schedule only; they don't change expenses or the dashboard's amount paid.
Importing a replacement requires confirmation and starts every new row as `Pending`.
Only the extracted rows are stored, not the uploaded PDF.

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
| GET | `/api/payment-schedule` | Yes | Current payment schedule in document order |
| POST | `/api/payment-schedule` | Yes | Import an `application/pdf` request body; requires `?replace=true` to overwrite |
| PATCH | `/api/payment-schedule/{id}` | Yes | Body `{status}` with `Paid` or `Pending`; updates that row only |

Amounts are integers in paise (1 rupee = 100 paise). Schedule percentages use basis points (`1000` represents `10%`).
