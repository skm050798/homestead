import os
from datetime import date, datetime
from pathlib import Path
from typing import Annotated

from contextlib import asynccontextmanager

from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import auth
from .db import Budget, BudgetHistory, Expense, SessionLocal, init_db, utc_now


MAX_PAISE = 99999999999999
PAGE_PATH = Path(__file__).resolve().parents[2] / "index.html"
EXPENSES_PAGE_PATH = Path(__file__).resolve().parents[2] / "expenses.html"
COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "true").lower() == "true"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Homestead Budget API", lifespan=lifespan)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def require_login(session_token: str | None = Cookie(default=None, alias=auth.COOKIE_NAME)) -> None:
    if not auth.verify_token(session_token):
        raise HTTPException(status_code=401, detail="Please log in.")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class BudgetIn(BaseModel):
    budget_paise: int = Field(ge=0, le=MAX_PAISE)
    paid_paise: int = Field(ge=0, le=MAX_PAISE)


class BudgetOut(BudgetIn):
    updated_at: datetime


NonEmptyText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class ExpenseIn(BaseModel):
    expense_date: date
    category: NonEmptyText
    vendor: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] = ""
    amount_paise: int = Field(ge=1, le=MAX_PAISE)
    notes: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""


class ExpenseOut(ExpenseIn):
    id: int


def adjust_paid(db: Session, delta_paise: int, now: datetime) -> None:
    """Add or remove an expense amount from the budget's amount paid."""
    budget = db.get(Budget, 1)
    if budget is None:
        budget = Budget(id=1, budget_paise=0, paid_paise=0, updated_at=now)
        db.add(budget)
    budget.paid_paise = max(0, budget.paid_paise + delta_paise)
    budget.updated_at = now
    db.add(BudgetHistory(budget_paise=budget.budget_paise, paid_paise=budget.paid_paise, saved_at=now))


@app.get("/")
def home_page() -> FileResponse:
    return FileResponse(PAGE_PATH)


@app.get("/expenses.html")
def expenses_page() -> FileResponse:
    return FileResponse(EXPENSES_PAGE_PATH)


@app.post("/api/login")
def login(body: LoginIn, response: Response) -> dict:
    if not auth.check_credentials(body.username, body.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password.")
    response.set_cookie(
        auth.COOKIE_NAME,
        auth.create_token(),
        max_age=auth.SESSION_SECONDS,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite="lax",
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(auth.COOKIE_NAME, httponly=True, secure=COOKIE_SECURE, samesite="lax")
    return {"ok": True}


@app.get("/api/me", dependencies=[Depends(require_login)])
def me() -> dict:
    return {"ok": True}


@app.get("/api/budget", response_model=BudgetOut, dependencies=[Depends(require_login)])
def get_budget(db: Session = Depends(get_db)) -> Budget:
    budget = db.get(Budget, 1)
    if budget is None:
        raise HTTPException(status_code=404, detail="No budget saved yet.")
    return budget


@app.put("/api/budget", response_model=BudgetOut, dependencies=[Depends(require_login)])
def save_budget(body: BudgetIn, db: Session = Depends(get_db)) -> Budget:
    now = utc_now()
    budget = db.get(Budget, 1)
    if budget is None:
        budget = Budget(id=1, budget_paise=body.budget_paise, paid_paise=body.paid_paise, updated_at=now)
        db.add(budget)
    else:
        budget.budget_paise = body.budget_paise
        budget.paid_paise = body.paid_paise
        budget.updated_at = now
    db.add(BudgetHistory(budget_paise=body.budget_paise, paid_paise=body.paid_paise, saved_at=now))
    db.commit()
    db.refresh(budget)
    return budget


@app.get("/api/budget/history", dependencies=[Depends(require_login)])
def budget_history(limit: int = 50, db: Session = Depends(get_db)) -> list[dict]:
    limit = min(max(limit, 1), 500)
    rows = db.scalars(select(BudgetHistory).order_by(BudgetHistory.saved_at.desc()).limit(limit)).all()
    return [
        {"budget_paise": row.budget_paise, "paid_paise": row.paid_paise, "saved_at": row.saved_at}
        for row in rows
    ]


@app.get("/api/expenses", response_model=list[ExpenseOut], dependencies=[Depends(require_login)])
def list_expenses(db: Session = Depends(get_db)) -> list[Expense]:
    return db.scalars(select(Expense).order_by(Expense.expense_date.desc(), Expense.id.desc())).all()


@app.post("/api/expenses", response_model=ExpenseOut, status_code=201, dependencies=[Depends(require_login)])
def add_expense(body: ExpenseIn, db: Session = Depends(get_db)) -> Expense:
    now = utc_now()
    expense = Expense(**body.model_dump(), created_at=now)
    db.add(expense)
    adjust_paid(db, body.amount_paise, now)
    db.commit()
    db.refresh(expense)
    return expense


@app.put("/api/expenses/{expense_id}", response_model=ExpenseOut, dependencies=[Depends(require_login)])
def update_expense(expense_id: int, body: ExpenseIn, db: Session = Depends(get_db)) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found.")
    now = utc_now()
    delta = body.amount_paise - expense.amount_paise
    for field, value in body.model_dump().items():
        setattr(expense, field, value)
    if delta:
        adjust_paid(db, delta, now)
    db.commit()
    db.refresh(expense)
    return expense


@app.delete("/api/expenses/{expense_id}", dependencies=[Depends(require_login)])
def delete_expense(expense_id: int, db: Session = Depends(get_db)) -> dict:
    expense = db.get(Expense, expense_id)
    if expense is None:
        raise HTTPException(status_code=404, detail="Expense not found.")
    adjust_paid(db, -expense.amount_paise, utc_now())
    db.delete(expense)
    db.commit()
    return {"ok": True}
