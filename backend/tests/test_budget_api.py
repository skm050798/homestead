import os
import tempfile

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'test.db')}"
os.environ["APP_USERNAME"] = "tester"
os.environ["APP_PASSWORD"] = "secret-pass"
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["COOKIE_SECURE"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def logged_in(client):
    response = client.post("/api/login", json={"username": "tester", "password": "secret-pass"})
    assert response.status_code == 200
    return client


def test_budget_requires_login(client):
    assert client.get("/api/budget").status_code == 401
    assert client.put("/api/budget", json={"budget_paise": 1, "paid_paise": 0}).status_code == 401


def test_wrong_password_is_rejected(client):
    response = client.post("/api/login", json={"username": "tester", "password": "wrong"})
    assert response.status_code == 401


def test_saved_amounts_are_returned_and_recorded_in_history(logged_in):
    client = logged_in
    assert client.get("/api/budget").status_code == 404

    saved = client.put("/api/budget", json={"budget_paise": 500000000, "paid_paise": 125000050})
    assert saved.status_code == 200

    loaded = client.get("/api/budget").json()
    assert loaded["budget_paise"] == 500000000
    assert loaded["paid_paise"] == 125000050

    client.put("/api/budget", json={"budget_paise": 600000000, "paid_paise": 0})
    history = client.get("/api/budget/history").json()
    assert len(history) == 2
    assert history[0]["budget_paise"] == 600000000


def test_negative_or_fractional_amounts_are_rejected(logged_in):
    client = logged_in
    assert client.put("/api/budget", json={"budget_paise": -1, "paid_paise": 0}).status_code == 422
    assert client.put("/api/budget", json={"budget_paise": 1.5, "paid_paise": 0}).status_code == 422


def test_expenses_adjust_amount_paid_on_add_edit_and_delete(logged_in):
    client = logged_in
    client.put("/api/budget", json={"budget_paise": 100000000, "paid_paise": 0})
    expense = {"expense_date": "2026-11-01", "category": "Cement", "vendor": "Sri Traders",
               "amount_paise": 2500000, "notes": "50 bags"}

    created = client.post("/api/expenses", json=expense)
    assert created.status_code == 201
    expense_id = created.json()["id"]
    assert client.get("/api/budget").json()["paid_paise"] == 2500000

    client.put(f"/api/expenses/{expense_id}", json={**expense, "amount_paise": 3000000})
    assert client.get("/api/budget").json()["paid_paise"] == 3000000

    assert client.delete(f"/api/expenses/{expense_id}").status_code == 200
    assert client.get("/api/budget").json()["paid_paise"] == 0
    assert client.get("/api/expenses").json() == []


def test_expense_requires_category_and_positive_amount(logged_in):
    client = logged_in
    base = {"expense_date": "2026-11-01", "category": "Labour", "amount_paise": 100}
    assert client.post("/api/expenses", json={**base, "category": "   "}).status_code == 422
    assert client.post("/api/expenses", json={**base, "amount_paise": 0}).status_code == 422
