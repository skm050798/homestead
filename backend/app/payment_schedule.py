import re
from decimal import Decimal
from io import BytesIO
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StringConstraints, ValidationError
from pypdf import PdfReader
from pypdf.errors import PyPdfError


MAX_PDF_BYTES = 5 * 1024 * 1024
MAX_PDF_PAGES = 20
MAX_PAISE = 99999999999999
PaymentStatus = Literal["Paid", "Pending"]


class PaymentStatusIn(BaseModel):
    status: PaymentStatus


class PaymentRow(PaymentStatusIn):
    milestone: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    percentage_bps: int = Field(ge=0, le=10000)
    amount_paise: int = Field(ge=1, le=MAX_PAISE)


COLUMN_GAP = re.compile(r"\t+| {2,}")
DESCRIPTION_HEADERS = {"milestone", "description"}
AMOUNT_HEADER = re.compile(r"amount(?:\s*(?:\((?:inr|\u20b9|rs\.?)\)|inr|\u20b9|rs\.?))?", re.IGNORECASE)
AMOUNT = re.compile(
    r"(?:\u20b9|INR|Rs\.?)?\s*"
    r"(?P<value>(?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]{1,2}(?:,[0-9]{2})*,[0-9]{3}|[0-9]+)"
    r"(?:\.[0-9]{1,2})?)",
    re.IGNORECASE,
)
TOTAL_LABELS = {"total", "subtotal", "sub total", "grand total", "total amount"}


class ScheduleImportError(ValueError):
    pass


def read_payment_schedule(pdf: bytes) -> list[PaymentRow]:
    if not pdf.startswith(b"%PDF-"):
        raise ScheduleImportError("Choose a valid PDF file.")
    try:
        reader = PdfReader(BytesIO(pdf))
        if reader.is_encrypted:
            raise ScheduleImportError("Upload an unlocked PDF.")
        if len(reader.pages) > MAX_PDF_PAGES:
            raise ScheduleImportError(f"Upload a PDF with at most {MAX_PDF_PAGES} pages.")
        pages = [page.extract_text(extraction_mode="layout") for page in reader.pages]
    except (PyPdfError, UnicodeError, RecursionError) as error:
        raise ScheduleImportError("This PDF could not be read. Try exporting it again.") from error

    rows: list[PaymentRow] = []
    description_index = amount_index = None
    column_count = 0
    for page in pages:
        for line in page.splitlines():
            cells = [cell.strip() for cell in COLUMN_GAP.split(line.strip().replace("\xa0", " "))]
            headings = [cell.casefold() for cell in cells]
            description = next((i for i, heading in enumerate(headings) if heading in DESCRIPTION_HEADERS), None)
            amount = next((i for i, heading in enumerate(headings) if AMOUNT_HEADER.fullmatch(heading)), None)
            if description is not None and amount is not None:
                description_index, amount_index = description, amount
                column_count = len(cells)
                continue
            if description_index is None or amount_index is None or len(cells) < 2:
                continue
            if headings[min(description_index, len(cells) - 1)] in TOTAL_LABELS or (
                len(cells) < column_count and headings[0] in TOTAL_LABELS
            ):
                continue
            if len(cells) != column_count:
                raise ScheduleImportError(f"Could not identify the columns in payment row {len(rows) + 1}.")
            match = AMOUNT.fullmatch(cells[amount_index])
            if not match:
                raise ScheduleImportError(f"Check the amount in payment row {len(rows) + 1}.")
            try:
                rows.append(PaymentRow(
                    milestone=" ".join(cells[description_index].split()),
                    percentage_bps=0,
                    amount_paise=int(Decimal(match["value"].replace(",", "")) * 100),
                    status="Pending",
                ))
            except ValidationError as error:
                raise ScheduleImportError(
                    f"Check the description and amount in payment row {len(rows) + 1}."
                ) from error

    if not rows:
        raise ScheduleImportError(
            "No payment rows found. Use a PDF with selectable text and columns Amount and Milestone or Description."
        )

    total = sum(row.amount_paise for row in rows)
    remainders = []
    for row in rows:
        row.percentage_bps, remainder = divmod(row.amount_paise * 10000, total)
        remainders.append(remainder)
    # Give leftover basis points to the largest remainders so the shares sum to 100%.
    leftover = 10000 - sum(row.percentage_bps for row in rows)
    for index in sorted(range(len(rows)), key=remainders.__getitem__, reverse=True)[:leftover]:
        rows[index].percentage_bps += 1
    return rows
