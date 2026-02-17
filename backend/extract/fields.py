"""Value parsers and the label vocabulary the extractor looks for.

The vocabulary was written from the four customer-PO layouts used for development (L1 to L4), the two
confirmation layouts and the delivery note. The fifth PO layout (L5) is held out to measure how the
extractor copes with a layout it was not written for; tests/test_extract.py checks that none of L5's own
labels crept in here.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

OUR_TRN = "100458213900003"  # the reseller's own TRN: any other TRN on a customer PO is the buyer's

LABELS = {
    # customer PO header
    "po_number": ["p.o. no.", "purchase order #", "po number", "order ref", "po no", "purchase order no"],
    "po_date": ["p.o. date", "order date", "date", "issue date", "po date"],
    "required_by": ["required delivery date", "deliver by", "needed by", "need by", "required by"],
    # distributor confirmation header
    "confirmation_no": ["confirmation no.", "ack ref", "confirmation number"],
    "referenced_po": ["your po ref", "customer po", "order ref", "po ref"],
    "eta": ["expected delivery", "eta"],
    # delivery note header
    "delivery_note_no": ["delivery note no.", "delivery note"],
    "tracking_number": ["tracking no.", "tracking number", "tracking"],
}

# Column headings of line-item tables, by the role of the column.
COLUMNS = {
    "line_no": ["s/n", "line", "ln", "#"],
    "part_number": ["item code", "part no.", "part number", "material", "sku", "item"],
    "description": ["description"],
    "qty": ["qty", "quantity", "qty confirmed"],
    "unit_price": ["unit price (aed)", "unit price", "unit cost", "price", "rate"],
    "amount": ["amount (aed)", "line total", "net value", "amount", "total"],
    "uom": ["uom"],
    "serials": ["serial numbers"],
    "remarks": ["remarks"],
}
# Where a heading word could mean two things, the more specific heading wins the role.
PART_PRIORITY = ["item code", "part no.", "part number", "material", "sku", "item"]

# Totals block under the table: which words point to which total.
TOTAL_WORDS = {"vat": ["vat"], "subtotal": ["sub", "net"], "total": ["total"]}

DATE_FORMATS = ["%d/%m/%Y", "%d-%b-%Y", "%Y-%m-%d", "%d.%m.%Y", "%d %b %Y", "%B %d, %Y", "%d %B %Y"]

MONEY = re.compile(r"^-?\d{1,3}(,\d{3})*\.\d{2}$|^-?\d+\.\d{2}$")
INTEGER = re.compile(r"^\d{1,6}$")
TRN = re.compile(r"\b100\d{12}\b")
PART = re.compile(r"^(?=.*[A-Z])(?=.*[\d-])[A-Z0-9][A-Z0-9.\-/]{3,39}$")
OUR_PO = re.compile(r"\bPO-\d{4}-\d{4}\b")
SUBSTITUTE = re.compile(r"(?:replaces|sub for)\s+([A-Z0-9][A-Z0-9.\-/]{3,39})", re.IGNORECASE)


def parse_date(text: str) -> date | None:
    text = text.strip().rstrip(".,")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(text: str) -> Decimal | None:
    text = text.strip()
    if not MONEY.match(text):
        return None
    try:
        return Decimal(text.replace(",", ""))
    except InvalidOperation:
        return None


def parse_int(text: str) -> int | None:
    text = text.strip()
    return int(text) if INTEGER.match(text) else None


def norm(text: str) -> str:
    """Lower case, colon and surrounding space removed: how labels are compared."""
    return re.sub(r"\s+", " ", text.strip().rstrip(":").lower())
