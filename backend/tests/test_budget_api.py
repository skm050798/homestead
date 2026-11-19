import os
import tempfile
from io import BytesIO

os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tempfile.mkdtemp(), 'test.db')}"
os.environ["APP_USERNAME"] = "tester"
os.environ["APP_PASSWORD"] = "secret-pass"
os.environ["SESSION_SECRET"] = "test-session-secret"
os.environ["COOKIE_SECURE"] = "false"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfWriter  # noqa: E402
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject  # noqa: E402

from app.main import app  # noqa: E402
from app.payment_schedule import read_payment_schedule  # noqa: E402


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


def schedule_pdf(*lines):
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Courier"),
            })
        })
    })
    stream = DecodedStreamObject()
    text = " ".join(f"1 0 0 1 50 {750 - i * 18} Tm ({line}) Tj" for i, line in enumerate(lines))
    stream.set_data(f"BT /F1 12 Tf {text} ET".encode("ascii"))
    page[NameObject("/Contents")] = stream
    pdf = BytesIO()
    writer.write(pdf)
    return pdf.getvalue()


def test_payment_schedule_has_its_own_page(client):
    path = "/payment-schedule.html"
    page = client.get(path)
    assert page.status_code == 200
    assert 'id="schedule-form"' in page.text
    assert 'id="schedule-rows"' in page.text
    assert f'href="{path}"' in client.get("/").text
    expenses_page = client.get("/expenses.html").text
    assert f'href="{path}"' in expenses_page
    assert 'id="schedule-form"' not in expenses_page


def test_import_and_update_payment_schedule_without_changing_expenses(logged_in):
    client = logged_in
    path = "/api/payment-schedule"
    headers = {"Content-Type": "application/pdf"}
    pdf = schedule_pdf(
        "Milestone                  %       Amount          Status",
        "Agreement Signing         99      Rs. 5,00,000    Paid",
        "Foundation Complete       N/A     Rs. 10,00,000   Unknown",
        "Ground Floor Slab         20      Rs. 10,00,000   Pending",
        "First Floor Slab          20      Rs. 10,00,000   Pending",
        "Plastering                15      Rs. 7,50,000    Pending",
        "Handover                  15      Rs. 7,50,000    Pending",
    )
    budget_before = client.get("/api/budget").json()
    expenses_before = client.get("/api/expenses").json()
    imported = client.post(path, headers=headers, content=pdf)
    assert imported.status_code == 201, imported.text
    rows = imported.json()
    assert [(r["milestone"], r["percentage_bps"], r["amount_paise"], r["status"]) for r in rows] == [
        ("Agreement Signing", 1000, 50000000, "Pending"),
        ("Foundation Complete", 2000, 100000000, "Pending"),
        ("Ground Floor Slab", 2000, 100000000, "Pending"),
        ("First Floor Slab", 2000, 100000000, "Pending"),
        ("Plastering", 1500, 75000000, "Pending"),
        ("Handover", 1500, 75000000, "Pending"),
    ]

    row_path = f"{path}/{rows[1]['id']}"
    assert client.patch(row_path, json={"status": "Paid"}).json() == {**rows[1], "status": "Paid"}
    rows[1]["status"] = "Paid"
    assert client.post(path, headers=headers, content=pdf).status_code == 409
    invalid_pdf = schedule_pdf(
        "Milestone                  %       Amount          Status",
        "Agreement Signing         10      Rs. 5,00,000    Paid",
        "Foundation Complete       20      TBD             Pending",
    )
    assert client.post(path + "?replace=true", headers=headers, content=invalid_pdf).status_code == 422
    assert client.get(path).json() == rows
    assert client.patch(row_path, json={"status": "Pending"}).json() == {**rows[1], "status": "Pending"}

    replacement = client.post(path + "?replace=true", headers=headers, content=pdf)
    assert replacement.status_code == 201
    assert all(row["status"] == "Pending" for row in replacement.json())
    assert client.get(path).json() == replacement.json()
    assert client.patch(row_path, json={"status": "Paid"}).status_code == 404
    assert client.get("/api/budget").json() == budget_before
    assert client.get("/api/expenses").json() == expenses_before


def test_import_uses_amount_and_description_only_and_excludes_total():
    rows = read_payment_schedule(schedule_pdf(
        "Amount (INR)     Description",
        "Rs. 1.01         Agreement Signing",
        "Rs. 1.01         Foundation Complete",
        "Rs. 1.01         Handover",
        "Rs. 3.03         Grand Total",
    ))
    assert [(row.milestone, row.amount_paise, row.percentage_bps, row.status) for row in rows] == [
        ("Agreement Signing", 101, 3334, "Pending"),
        ("Foundation Complete", 101, 3333, "Pending"),
        ("Handover", 101, 3333, "Pending"),
    ]


def test_schedule_upload_validates_access_and_pdf(logged_in):
    path = "/api/payment-schedule"
    headers = {"Content-Type": "application/pdf"}
    assert logged_in.post(path, headers=headers, content=b"not a PDF").status_code == 422
    assert logged_in.post(path, headers=headers, content=b"%PDF-1.7\n").status_code == 422
    assert logged_in.post(path, headers=headers, content=b"0" * (5 * 1024 * 1024 + 1)).status_code == 413
    assert logged_in.post(path, headers=headers, content=schedule_pdf("No schedule")).status_code == 422
    logged_in.post("/api/logout")
    assert logged_in.get(path).status_code == 401
    assert logged_in.post(path, headers=headers, content=b"").status_code == 401
    assert logged_in.patch(path + "/1", json={"status": "Paid"}).status_code == 401
