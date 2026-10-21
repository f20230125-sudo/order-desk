"""Draw the paper documents of an order as PDFs, each layout the way a different organisation would.

Layouts differ in exactly the ways that make extraction hard in real life: label wording, date formats,
column order and headings, ruled versus unruled tables, wrapped descriptions, a second page of terms.
L5 is held out: it is never looked at while the extractor is written, so its score is an honest test.
"""

import io
from collections.abc import Callable
from datetime import date
from decimal import Decimal

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen.canvas import Canvas

from backend.check.model import Line
from synth.catalogue import PRODUCT_BY_PART, US
from synth.scenario import SynthOrder

GREY = Color(0.45, 0.45, 0.45)
LIGHT = Color(0.85, 0.85, 0.85)


def amount(x: Decimal) -> str:
    return f"{x:,.2f}"


def wrap(text: str, width_chars: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        if cur and len(cur) + 1 + len(w) > width_chars:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        lines.append(cur)
    return lines or [""]


class Doc:
    """A thin helper over the reportlab canvas, measuring from the top of the page like a person does."""

    def __init__(self, pagesize=A4, title: str = ""):
        self.buf = io.BytesIO()
        self.c = Canvas(self.buf, pagesize=pagesize, invariant=1)
        self.c.setTitle(title)
        self.c.setAuthor("synthetic")
        self.w, self.h = pagesize

    def text(self, x, y, s, size=9, bold=False, color=black, right=False):
        self.c.setFillColor(color)
        self.c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        if right:
            self.c.drawRightString(x, self.h - y, s)
        else:
            self.c.drawString(x, self.h - y, s)

    def hline(self, x1, x2, y, width=0.6, color=black):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(x1, self.h - y, x2, self.h - y)

    def vline(self, x, y1, y2, width=0.6, color=black):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(width)
        self.c.line(x, self.h - y1, x, self.h - y2)

    def rect(self, x, y, w, h, width=0.6):
        self.c.setLineWidth(width)
        self.c.rect(x, self.h - y - h, w, h, stroke=1, fill=0)

    def new_page(self):
        self.c.showPage()

    def bytes(self) -> bytes:
        self.c.save()
        return self.buf.getvalue()


def _table(
    doc: Doc,
    top: float,
    columns: list[tuple[str, float, str]],
    rows: list[list[str]],
    ruled: bool,
    wrap_col: int | None = None,
    wrap_chars: int = 40,
    row_gap: float = 13,
    header_bold: bool = True,
) -> float:
    """Draw a line-item table. columns: (heading, x, align 'l'|'r'). Returns the y below the table."""
    x_left = columns[0][1] - 4
    x_right = doc.w - 36
    if ruled:
        doc.hline(x_left, x_right, top - 10)
    for heading, x, align in columns:
        doc.text(x, top, heading, size=8.5, bold=header_bold, right=(align == "r"))
    y = top + 6
    if ruled:
        doc.hline(x_left, x_right, y)
    else:
        doc.hline(x_left, x_right, y, width=0.4, color=GREY)
    y += 12
    for row in rows:
        cells = list(row)
        extra: list[str] = []
        if wrap_col is not None:
            parts = wrap(cells[wrap_col], wrap_chars)
            cells[wrap_col], extra = parts[0], parts[1:]
        for (_heading, x, align), cell in zip(columns, cells, strict=True):
            doc.text(x, y, cell, right=(align == "r"))
        for k, more in enumerate(extra, start=1):
            doc.text(columns[wrap_col][1], y + k * 10, more, color=GREY)
        bottom = y + len(extra) * 10 + 5
        if ruled:
            doc.hline(x_left, x_right, bottom)
        y = bottom + row_gap
    return y


def _lines_rows(lines: list[Line], fmt: Callable[[Line], list[str]]) -> list[list[str]]:
    return [fmt(line) for line in lines]


def _totals(
    doc: Doc,
    y: float,
    labels: tuple[str, str, str],
    values: tuple[Decimal, Decimal, Decimal],
    x_label: float,
    x_value: float,
    bold_last: bool = True,
) -> float:
    for k, (label, value) in enumerate(zip(labels, values, strict=True)):
        last = k == 2
        doc.text(x_label, y, label, bold=last and bold_last)
        doc.text(x_value, y, amount(value), bold=last and bold_last, right=True)
        y += 14
    return y


# ---------------------------------------------------------------- customer purchase orders


def customer_po_l1(o: SynthOrder) -> bytes:
    """Government tender style: boxed header fields, fully ruled table, dd/mm/yyyy."""
    po = o.customer_po
    d = Doc(title=f"Purchase Order {po.po_number}")
    d.text(36, 50, o.customer.name.upper(), size=14, bold=True)
    d.text(36, 64, f"{o.customer.address}, {o.customer.emirate}, United Arab Emirates", size=8, color=GREY)
    d.text(36, 76, f"Procurement Section    TRN: {o.customer.trn}", size=8, color=GREY)
    d.text(d.w - 36, 50, "PURCHASE ORDER", size=16, bold=True, right=True)
    boxes = [
        ("P.O. No.", po.po_number),
        ("P.O. Date", po.po_date.strftime("%d/%m/%Y")),
        ("Required Delivery Date", po.required_by.strftime("%d/%m/%Y")),
        ("Currency", po.currency),
    ]
    x = 36
    for label, value in boxes:
        d.rect(x, 92, 130, 34)
        d.text(x + 5, 104, label, size=7.5, color=GREY)
        d.text(x + 5, 119, value, size=10, bold=True)
        x += 131
    d.text(36, 148, "Vendor:", size=8, bold=True)
    d.text(80, 148, US["name"], size=8)
    d.text(80, 159, US["address"], size=8)
    d.text(80, 170, f"Vendor TRN: {US['trn']}", size=8)
    d.text(330, 148, "Deliver to:", size=8, bold=True)
    for k, part in enumerate(wrap(o.deliver_to, 48)):
        d.text(385, 148 + k * 11, part, size=8)
    cols = [
        ("S/N", 40, "l"),
        ("Item Code", 66, "l"),
        ("Description", 150, "l"),
        ("Qty", 400, "r"),
        ("Unit Price (AED)", 478, "r"),
        ("Amount (AED)", d.w - 40, "r"),
    ]
    rows = _lines_rows(
        po.lines,
        lambda ln: [
            str(ln.line_no),
            ln.part_number,
            ln.description,
            str(ln.qty),
            amount(ln.unit_price),
            amount(ln.qty * ln.unit_price),
        ],
    )
    y = _table(d, 210, cols, rows, ruled=True, wrap_col=2, wrap_chars=44)
    y = _totals(
        d,
        y + 6,
        ("Sub Total", "VAT 5%", "Grand Total"),
        (po.subtotal, po.vat_amount, po.total),
        400,
        d.w - 40,
    )
    d.text(
        36,
        y + 24,
        "Terms: Delivery to site within the required date. Invoice must quote the P.O. No.",
        size=7.5,
        color=GREY,
    )
    d.text(36, y + 36, f"Requested by: {o.contact}", size=8)
    d.text(36, y + 70, "Authorised Signatory ____________________", size=8)
    return d.bytes()


def customer_po_l2(o: SynthOrder) -> bytes:
    """Bank style: label-colon header, unruled table, dd-Mon-yyyy, different total wording."""
    po = o.customer_po
    d = Doc(title=f"PO {po.po_number}")
    d.text(36, 48, o.customer.name, size=15, bold=True)
    d.text(36, 62, "Information Technology Procurement", size=9, color=GREY)
    d.hline(36, d.w - 36, 74, width=1.2)
    fields = [
        ("Purchase Order #:", po.po_number),
        ("Order Date:", po.po_date.strftime("%d-%b-%Y")),
        ("Deliver By:", po.required_by.strftime("%d-%b-%Y")),
        ("Buyer TRN:", o.customer.trn),
    ]
    for k, (label, value) in enumerate(fields):
        d.text(36, 96 + k * 13, label, size=9, bold=True)
        d.text(140, 96 + k * 13, value, size=9)
    d.text(330, 96, "Supplier", size=9, bold=True)
    d.text(330, 109, US["name"], size=9)
    d.text(330, 122, f"TRN {US['trn']}", size=9)
    d.text(330, 135, f"Contact: {o.contact}", size=9)
    cols = [
        ("Line", 40, "l"),
        ("Part No.", 70, "l"),
        ("Description", 160, "l"),
        ("Quantity", 410, "r"),
        ("Unit Cost", 482, "r"),
        ("Line Total", d.w - 40, "r"),
    ]
    rows = _lines_rows(
        po.lines,
        lambda ln: [
            str(ln.line_no),
            ln.part_number,
            ln.description,
            str(ln.qty),
            amount(ln.unit_price),
            amount(ln.qty * ln.unit_price),
        ],
    )
    y = _table(d, 180, cols, rows, ruled=False, wrap_col=2, wrap_chars=44)
    d.hline(380, d.w - 36, y - 4, width=0.4, color=GREY)
    y = _totals(
        d,
        y + 10,
        ("Net Amount", "VAT", "Total Amount (AED)"),
        (po.subtotal, po.vat_amount, po.total),
        380,
        d.w - 40,
    )
    d.text(
        36, y + 30, "This order is subject to the bank's standard procurement terms.", size=7.5, color=GREY
    )
    return d.bytes()


def customer_po_l3(o: SynthOrder) -> bytes:
    """School style: plain, ISO dates, short headings, description not wrapped (shortened)."""
    po = o.customer_po
    d = Doc(title=f"Purchase order {po.po_number}")
    d.text(36, 52, o.customer.name, size=13, bold=True)
    d.text(36, 66, f"{o.customer.address}, {o.customer.emirate}", size=8, color=GREY)
    d.text(36, 100, "Purchase order", size=18, bold=True)
    d.text(36, 124, f"PO Number  {po.po_number}", size=10)
    d.text(36, 138, f"Date  {po.po_date.isoformat()}", size=10)
    d.text(36, 152, f"Needed by  {po.required_by.isoformat()}", size=10)
    d.text(330, 124, f"To: {US['name']}", size=9)
    d.text(330, 138, f"TRN {US['trn']}", size=9)
    d.text(330, 152, f"School TRN {o.customer.trn}", size=9)
    cols = [
        ("Item", 40, "l"),
        ("Description", 130, "l"),
        ("Qty", 420, "r"),
        ("Rate", 488, "r"),
        ("Total", d.w - 40, "r"),
    ]
    rows = _lines_rows(
        po.lines,
        lambda ln: [
            ln.part_number,
            ln.description[:52],
            str(ln.qty),
            amount(ln.unit_price),
            amount(ln.qty * ln.unit_price),
        ],
    )
    y = _table(d, 190, cols, rows, ruled=True)
    y = _totals(
        d,
        y + 6,
        ("Subtotal", "VAT (5%)", "Total (AED)"),
        (po.subtotal, po.vat_amount, po.total),
        420,
        d.w - 40,
    )
    d.text(36, y + 26, f"Approved by the Bursar. Questions to {o.contact}.", size=8, color=GREY)
    return d.bytes()


def customer_po_l4(o: SynthOrder) -> bytes:
    """Enterprise ERP style: dotted dates, unit of measure column, terms on a second page."""
    po = o.customer_po
    d = Doc(title=f"Order {po.po_number}")
    d.text(36, 46, o.customer.name, size=12, bold=True)
    d.text(d.w - 36, 46, "Purchase Order", size=12, bold=True, right=True)
    d.hline(36, d.w - 36, 54)
    fields = [
        ("Order Ref:", po.po_number),
        ("Issue Date:", po.po_date.strftime("%d.%m.%Y")),
        ("Need By:", po.required_by.strftime("%d.%m.%Y")),
        ("Our VAT Reg:", o.customer.trn),
        ("Supplier:", US["name"]),
        ("Supplier VAT Reg:", US["trn"]),
    ]
    for k, (label, value) in enumerate(fields):
        col, row = divmod(k, 3)
        d.text(36 + col * 270, 74 + row * 13, label, size=8.5, color=GREY)
        d.text(126 + col * 270, 74 + row * 13, value, size=8.5)
    d.text(36, 124, f"Ship to: {o.deliver_to}", size=8.5)
    cols = [
        ("#", 40, "l"),
        ("Material", 58, "l"),
        ("Description", 150, "l"),
        ("Qty", 392, "r"),
        ("UoM", 400, "l"),
        ("Price", 482, "r"),
        ("Net Value", d.w - 40, "r"),
    ]
    rows = _lines_rows(
        po.lines,
        lambda ln: [
            str(ln.line_no * 10),
            ln.part_number,
            ln.description,
            str(ln.qty),
            "EA",
            amount(ln.unit_price),
            amount(ln.qty * ln.unit_price),
        ],
    )
    y = _table(d, 160, cols, rows, ruled=False, wrap_col=2, wrap_chars=42, row_gap=10)
    d.hline(36, d.w - 36, y - 4)
    y = _totals(
        d,
        y + 10,
        ("Total Net Value", "Output VAT 5%", "Total Order Value"),
        (po.subtotal, po.vat_amount, po.total),
        380,
        d.w - 40,
    )
    d.text(36, d.h - 40, "Page 1 of 2", size=7.5, color=GREY)
    d.new_page()
    d.text(36, 50, "General terms and conditions of purchase", size=11, bold=True)
    terms = (
        "1. Delivery: goods are delivered to the address above on or before the need-by date. "
        "2. Invoices must quote the order reference and the supplier VAT registration number. "
        "3. Partial deliveries need the buyer's written approval. "
        "4. Serial numbers of all serialised equipment are listed on the delivery note."
    )
    for k, part in enumerate(wrap(terms, 100)):
        d.text(36, 72 + k * 12, part, size=8.5)
    d.text(36, d.h - 40, "Page 2 of 2", size=7.5, color=GREY)
    return d.bytes()


def customer_po_l5(o: SynthOrder) -> bytes:
    """Held out. Landscape, quantity first, long-form dates, different label wording everywhere."""
    po = o.customer_po
    d = Doc(pagesize=landscape(A4), title=f"Order {po.po_number}")
    d.text(36, 44, "ORDER FORM", size=20, bold=True)
    d.text(36, 62, o.customer.name, size=11)
    d.text(36, 76, f"Tax registration {o.customer.trn}", size=8.5, color=GREY)
    fields = [
        ("Order No.", po.po_number),
        ("Dated", po.po_date.strftime("%B %d, %Y")),
        ("Delivery Required", po.required_by.strftime("%B %d, %Y")),
    ]
    for k, (label, value) in enumerate(fields):
        d.text(480, 44 + k * 16, label, size=9, color=GREY)
        d.text(590, 44 + k * 16, value, size=10, bold=True)
    d.text(36, 104, f"Supplier: {US['name']} (TRN {US['trn']})", size=9)
    cols = [
        ("Qty", 52, "r"),
        ("Part Number", 70, "l"),
        ("Description", 190, "l"),
        ("Unit Price", 640, "r"),
        ("Extended", d.w - 40, "r"),
    ]
    rows = _lines_rows(
        po.lines,
        lambda ln: [
            str(ln.qty),
            ln.part_number,
            ln.description,
            amount(ln.unit_price),
            amount(ln.qty * ln.unit_price),
        ],
    )
    y = _table(d, 140, cols, rows, ruled=True, wrap_col=2, wrap_chars=80)
    y = _totals(
        d,
        y + 6,
        ("Taxable Value", "Tax @ 5%", "Amount Payable"),
        (po.subtotal, po.vat_amount, po.total),
        600,
        d.w - 40,
    )
    d.text(36, y + 20, f"Contact {o.contact}", size=8.5, color=GREY)
    return d.bytes()


CUSTOMER_PO = {
    "L1": customer_po_l1,
    "L2": customer_po_l2,
    "L3": customer_po_l3,
    "L4": customer_po_l4,
    "L5": customer_po_l5,
}


# ---------------------------------------------------------------- distributor confirmations


def confirmation_a(o: SynthOrder) -> bytes:
    conf = o.confirmation
    d = Doc(title=f"Sales order confirmation {conf.confirmation_no}")
    d.text(36, 48, o.distributor.name, size=13, bold=True)
    d.text(
        36,
        61,
        f"{o.distributor.address}, {o.distributor.emirate}    TRN {o.distributor.trn}",
        size=8,
        color=GREY,
    )
    d.text(36, 96, "SALES ORDER CONFIRMATION", size=14, bold=True)
    fields = [
        ("Confirmation No.", conf.confirmation_no),
        ("Your PO Ref", conf.referenced_po),
        ("Expected Delivery", conf.eta.strftime("%d/%m/%Y")),
        ("Customer", US["name"]),
    ]
    for k, (label, value) in enumerate(fields):
        d.text(36, 118 + k * 13, label, size=9, color=GREY)
        d.text(150, 118 + k * 13, value, size=9, bold=k < 3)
    cols = [
        ("Ln", 40, "l"),
        ("Part Number", 62, "l"),
        ("Description", 160, "l"),
        ("Qty", 412, "r"),
        ("Unit Price", 484, "r"),
        ("Total", d.w - 40, "r"),
    ]
    rows = []
    for ln in conf.lines:
        desc = ln.description + (f" (replaces {ln.substitutes_part})" if ln.substitutes_part else "")
        rows.append(
            [
                str(ln.line_no),
                ln.part_number,
                desc,
                str(ln.qty),
                amount(ln.unit_price),
                amount(ln.qty * ln.unit_price),
            ]
        )
    y = _table(d, 190, cols, rows, ruled=True, wrap_col=2, wrap_chars=44)
    net = sum((ln.qty * ln.unit_price for ln in conf.lines), Decimal(0))
    vat = (net * Decimal("0.05")).quantize(Decimal("0.01"))
    _totals(d, y + 6, ("Net", "VAT 5%", "Total AED"), (net, vat, net + vat), 412, d.w - 40)
    return d.bytes()


def confirmation_b(o: SynthOrder) -> bytes:
    conf = o.confirmation
    d = Doc(title=f"Order acknowledgement {conf.confirmation_no}")
    d.text(d.w - 36, 48, o.distributor.name, size=12, bold=True, right=True)
    d.text(36, 48, "Order Acknowledgement", size=16, bold=True)
    d.text(36, 76, f"Ack Ref: {conf.confirmation_no}", size=9.5)
    d.text(36, 90, f"Customer PO: {conf.referenced_po}", size=9.5)
    d.text(36, 104, f"ETA: {conf.eta.strftime('%d %b %Y')}", size=9.5)
    d.text(330, 76, f"Bill to: {US['name']}", size=9)
    cols = [
        ("Item", 40, "l"),
        ("SKU", 70, "l"),
        ("Qty Confirmed", 250, "r"),
        ("Price", 330, "r"),
        ("Amount", 420, "r"),
        ("Remarks", 440, "l"),
    ]
    rows = []
    for ln in conf.lines:
        remark = f"Sub for {ln.substitutes_part}" if ln.substitutes_part else ""
        rows.append(
            [
                str(ln.line_no),
                ln.part_number,
                str(ln.qty),
                amount(ln.unit_price),
                amount(ln.qty * ln.unit_price),
                remark,
            ]
        )
    _table(d, 140, cols, rows, ruled=False)
    return d.bytes()


CONFIRMATION = {"A": confirmation_a, "B": confirmation_b}


# ---------------------------------------------------------------- delivery note (inbound)


def delivery_note(o: SynthOrder, k: int = 0) -> bytes:
    ship = o.inbound[k]
    d = Doc(title=f"Delivery note {ship.reference}")
    d.text(36, 48, o.distributor.name, size=12, bold=True)
    d.text(d.w - 36, 48, "DELIVERY NOTE", size=14, bold=True, right=True)
    fields = [
        ("Delivery Note No.", ship.reference),
        ("Order Ref", o.our_po.our_po_number),
        ("Carrier", o.carrier.name),
        ("Tracking No.", o.tracking[ship.reference]),
        ("Deliver to", f"{US['name']}, {US['address']}"),
    ]
    for k2, (label, value) in enumerate(fields):
        d.text(36, 76 + k2 * 13, label, size=9, color=GREY)
        d.text(150, 76 + k2 * 13, value, size=9)
    if ship.marked_partial:
        d.text(36, 150, "PART DELIVERY - balance to follow", size=10, bold=True)
    cols = [
        ("Part Number", 40, "l"),
        ("Description", 140, "l"),
        ("Qty", 330, "r"),
        ("Serial Numbers", 346, "l"),
    ]
    y = 180
    d.hline(36, d.w - 36, y - 10)
    for heading, x, align in cols:
        d.text(x, y, heading, size=8.5, bold=True, right=(align == "r"))
    y += 18
    for sl in ship.lines:
        prod = PRODUCT_BY_PART[sl.part_number]
        d.text(40, y, sl.part_number)
        d.text(140, y, wrap(prod.description, 32)[0])
        d.text(330, y, str(sl.qty), right=True)
        serial_lines = wrap(", ".join(sl.serials), 38) if sl.serials else ["not serialised"]
        for j, s in enumerate(serial_lines):
            d.text(346, y + j * 10, s, color=black if sl.serials else GREY)
        y += max(1, len(serial_lines)) * 10 + 10
    d.hline(36, d.w - 36, y)
    d.text(36, y + 30, "Received in good condition: ____________________   Date: __________", size=8.5)
    return d.bytes()


def render_date(x: date) -> str:
    return x.strftime("%d %b %Y")
