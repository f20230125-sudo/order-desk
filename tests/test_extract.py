"""The extractor, one document per layout, plus the rules that keep the held-out score honest."""

from datetime import date
from decimal import Decimal
from io import BytesIO

import pytest
from reportlab.pdfgen import canvas

from backend.extract import fields
from backend.extract.detect import extract, sniff
from backend.extract.pdf import extract_pdf
from synth.generate import documents_for
from synth.scenario import build

ORDERS = {o.key: o for o in build()}


def _doc(order_key: str, suffix: str) -> tuple[bytes, dict]:
    for name, data, truth in documents_for(ORDERS[order_key], held_out=True):
        if name.endswith(suffix):
            return data, truth
    raise LookupError(order_key + suffix)


def _first_order(predicate):
    return next(o for o in ORDERS.values() if predicate(o))


@pytest.mark.parametrize("layout", ["L1", "L2", "L3", "L4"])
def test_customer_po_layouts(layout):
    order = _first_order(lambda o: o.customer_layout == layout)
    data, truth = _doc(order.key, f"customer-po-{layout}.pdf")
    got = extract_pdf(data)
    assert got["kind"] == "customer_po"
    f = got["fields"]
    assert f["po_number"]["value"] == truth["fields"]["po_number"]
    assert f["po_date"]["value"] == date.fromisoformat(truth["fields"]["po_date"])
    assert f["total"]["value"] == Decimal(truth["fields"]["total"])
    assert [ln["part_number"]["value"] for ln in got["lines"]] == [x["part_number"] for x in truth["lines"]]
    assert [ln["qty"]["value"] for ln in got["lines"]] == [x["qty"] for x in truth["lines"]]


def test_every_value_says_where_it_came_from():
    order = _first_order(lambda o: o.customer_layout == "L1")
    data, _ = _doc(order.key, "customer-po-L1.pdf")
    got = extract_pdf(data)
    po = got["fields"]["po_number"]
    assert po["page"] == 0 and len(po["bbox"]) == 4
    x0, top, x1, bottom = po["bbox"]
    width, height = got["page_sizes"][0]
    assert 0 <= x0 < x1 <= width and 0 <= top < bottom <= height
    assert po["rule"].startswith("label")


def test_confirmation_reads_substitutions():
    order = _first_order(lambda o: o.confirmation and any(x.substitutes_part for x in o.confirmation.lines))
    data, truth = _doc(order.key, f"confirmation-{order.confirmation_layout}.pdf")
    got = extract_pdf(data)
    subs = {
        ln["part_number"]["value"]: ln["substitutes_part"]["value"]
        for ln in got["lines"]
        if "substitutes_part" in ln
    }
    expected = {x["part_number"]: x["substitutes_part"] for x in truth["lines"] if "substitutes_part" in x}
    assert subs == expected and subs


def test_delivery_note_serials_and_partial_flag():
    order = _first_order(lambda o: o.inbound and o.inbound[0].marked_partial)
    data, truth = _doc(order.key, "delivery-note-1.pdf")
    got = extract_pdf(data)
    assert got["fields"]["marked_partial"]["value"] is True
    assert [ln["serials"]["value"] for ln in got["lines"]] == [x["serials"] for x in truth["lines"]]


@pytest.mark.parametrize("carrier", ["AAF", "SGC"])  # serials attached as CSV, and typed in the body
def test_dispatch_email(carrier):
    order = _first_order(lambda o: o.inbound and o.carrier.short_code == carrier)
    data, truth = _doc(order.key, "dispatch-1.eml")
    mime, got = extract(data)
    assert mime == "message/rfc822"
    assert got["fields"]["tracking_number"]["value"] == truth["fields"]["tracking_number"]
    assert got["fields"]["referenced_po"]["value"] == truth["fields"]["referenced_po"]
    assert [ln["serials"]["value"] for ln in got["lines"]] == [x["serials"] for x in truth["lines"]]


def test_unknown_labels_fall_back_with_low_confidence():
    order = _first_order(lambda o: True)
    data, truth = _doc(order.key, "customer-po-L5.pdf")
    got = extract_pdf(data)
    assert got["fields"]["po_date"]["value"] == date.fromisoformat(truth["fields"]["po_date"])
    assert got["fields"]["po_date"]["confidence"] <= 0.6
    assert got["fields"]["po_date"]["rule"].startswith("date order")


def test_held_out_labels_are_not_in_the_vocabulary():
    """L5 is the held-out layout. If its own wording appears in the label lists, its score means nothing."""
    l5_only = [
        "order no.",
        "dated",
        "delivery required",
        "taxable value",
        "tax @ 5%",
        "amount payable",
        "extended",
        "order form",
    ]
    vocabulary = {x for group in fields.LABELS.values() for x in group}
    vocabulary |= {x for group in fields.COLUMNS.values() for x in group}
    vocabulary |= {x for group in fields.TOTAL_WORDS.values() for x in group}
    assert not vocabulary & set(l5_only)


def test_files_are_recognised_by_content_not_name():
    assert sniff(b"%PDF-1.7\n...") == "application/pdf"
    assert sniff(b"From: a@b.example\r\nSubject: x\r\n\r\nbody") == "message/rfc822"
    assert sniff(b"MZ\x90\x00 executable") is None
    assert sniff(b"<html><body>not an email</body></html>") is None
    with pytest.raises(ValueError):
        extract(b"PK\x03\x04 a zip file")


@pytest.mark.parametrize(
    "text,expected",
    [
        ("15/10/2026", date(2026, 10, 15)),
        ("18-Oct-2026", date(2026, 10, 18)),
        ("2026-10-17", date(2026, 10, 17)),
        ("30.09.2026", date(2026, 9, 30)),
        ("19 Oct 2026", date(2026, 10, 19)),
        ("31/02/2026", None),
        ("hello", None),
    ],
)
def test_dates(text, expected):
    assert fields.parse_date(text) == expected


def test_money_and_quantities():
    assert fields.parse_money("1,234,567.89") == Decimal("1234567.89")
    assert fields.parse_money("12,34.00") is None
    assert fields.parse_money("1.92") == Decimal("1.92")  # looks like money; column alignment decides
    assert fields.parse_int("250") == 250 and fields.parse_int("2.5") is None


def test_multipage_pdf_warns_that_extraction_is_incomplete():
    out = BytesIO()
    pdf = canvas.Canvas(out)
    for part in ("PER760-XS2", "VVF-CORE-1Y"):
        pdf.drawString(40, 800, "Purchase Order")
        for x, text in ((40, "Part Number"), (200, "Description"), (350, "Qty"), (410, "Unit Price")):
            pdf.drawString(x, 750, text)
        for x, text in ((40, part), (200, "Item"), (350, "1"), (410, "100.00")):
            pdf.drawString(x, 730, text)
        pdf.showPage()
    pdf.save()
    got = extract_pdf(out.getvalue())
    assert any("incomplete" in w.lower() and "page" in w.lower() for w in got["warnings"])
