"""Read a purchase order, a distributor confirmation or a delivery note from a PDF.

No model and no template per sender: words come out of the PDF with their positions (pdfplumber), and
the reader works the way a person does. Header values sit to the right of a label or in the box under it;
the line-item table starts at a row of column headings, and each value is filed under the heading it
lines up with; the totals block follows the table. Every value keeps the box it was read from (page
number and x0, top, x1, bottom in PDF points from the top-left corner), so the screen can show where it
came from, plus a confidence and the rule that produced it.
"""

import io
import re
from dataclasses import dataclass
from decimal import Decimal

import pdfplumber

from backend.extract import EXTRACTOR_VERSION
from backend.extract.fields import (
    COLUMNS,
    LABELS,
    OUR_PO,
    OUR_TRN,
    PART,
    PART_PRIORITY,
    SUBSTITUTE,
    TOTAL_WORDS,
    TRN,
    norm,
    parse_date,
    parse_int,
    parse_money,
)

NUMERIC = {"qty", "unit_price", "amount", "line_no"}
STOP_WORDS = ("page ", "terms", "received in good condition", "general terms", "this order is subject")
HEADER_FIELDS = {
    "customer_po": ["po_number", "po_date", "required_by"],
    "vendor_confirmation": ["confirmation_no", "referenced_po", "eta"],
    "delivery_note": ["delivery_note_no", "referenced_po", "tracking_number"],
}
DATE_FIELDS = {"po_date", "required_by", "eta"}


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    page: int


@dataclass
class TextLine:
    words: list[Word]
    page: int

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def _box(words: list[Word]) -> list[float]:
    return [
        round(min(w.x0 for w in words), 1),
        round(min(w.top for w in words), 1),
        round(max(w.x1 for w in words), 1),
        round(max(w.bottom for w in words), 1),
    ]


def _field(value, words: list[Word] | None, confidence: float, rule: str) -> dict:
    out = {"value": value, "confidence": round(confidence, 2), "rule": rule}
    if words:
        out["page"] = words[0].page
        out["bbox"] = _box(words)
    return out


def read_lines(pdf_bytes: bytes) -> tuple[list[TextLine], list[list[float]]]:
    """All words of all pages, grouped into visual lines (same baseline within 3 points)."""
    lines: list[TextLine] = []
    sizes = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for p, page in enumerate(pdf.pages):
            sizes.append([float(page.width), float(page.height)])
            words = [
                Word(w["text"], float(w["x0"]), float(w["x1"]), float(w["top"]), float(w["bottom"]), p)
                for w in page.extract_words(keep_blank_chars=False, x_tolerance=1.5, y_tolerance=2)
            ]
            words.sort(key=lambda w: (round(w.top), w.x0))
            current: list[Word] = []
            for w in words:
                if current and abs(w.top - current[0].top) > 3:
                    lines.append(TextLine(sorted(current, key=lambda x: x.x0), p))
                    current = []
                current.append(w)
            if current:
                lines.append(TextLine(sorted(current, key=lambda x: x.x0), p))
    return lines, sizes


def classify(lines: list[TextLine]) -> str:
    # The title is at the top of the first page; later pages (terms) mention other documents by name.
    text = " ".join(line.text.lower() for line in lines[:8] if line.page == 0)
    if "delivery note" in text:
        return "delivery_note"
    if "confirmation" in text or "acknowledg" in text:
        return "vendor_confirmation"
    return "customer_po"


# ---------------------------------------------------------------- header fields


def _label_spans(
    line: TextLine, labels: dict[str, list[str]], wanted: set[str]
) -> list[tuple[str, int, int]]:
    """Find labels on a line, longest first, left to right: (field, first word index, index after).
    The same words can label different fields on different documents ("Order Ref" is the customer's PO
    number on a PO, and our PO number on a delivery note): the fields of this kind of document win."""
    phrases = sorted(
        ((field, label) for field, ls in labels.items() for label in ls),
        key=lambda fl: (-len(fl[1].split()), fl[0] not in wanted),
    )
    toks = [norm(w.text) for w in line.words]
    spans, i = [], 0
    while i < len(toks):
        hit = None
        for field, label in phrases:
            n = len(label.split())
            if i + n <= len(toks) and norm(" ".join(toks[i : i + n])) == label:
                # A label ends at a colon or is followed by a gap; "Date" inside a sentence is not a label.
                hit = (field, i, i + n)
                break
        if hit:
            spans.append(hit)
            i = hit[2]
        else:
            i += 1
    return spans


def _valid(field: str, text: str):
    text = text.strip().strip(":").strip()
    if not text:
        return None
    if field in DATE_FIELDS:
        return parse_date(text)
    if field == "referenced_po":
        m = OUR_PO.search(text)
        return m.group(0) if m else (text if re.search(r"\d", text) and " " not in text else None)
    if field == "tracking_number":
        return text if re.fullmatch(r"[A-Z0-9][A-Z0-9\-]{6,24}", text) else None
    # identifiers: one token, with a digit in it
    return text if re.search(r"\d", text) and " " not in text else None


def header_fields(lines: list[TextLine], kind: str, stop_top: tuple[int, float] | None) -> dict:
    wanted = {f: LABELS[f] for f in HEADER_FIELDS[kind]}
    all_labels = {f: v for f, v in LABELS.items()}
    found: dict[str, dict] = {}
    for idx, line in enumerate(lines):
        if stop_top and (line.page, line.top) >= stop_top:
            break
        spans = _label_spans(line, all_labels, set(wanted))
        starts = [s[1] for s in spans]
        for field, a, b in spans:
            if field not in wanted or field in found:
                continue
            nxt = min([s for s in starts if s > a] + [len(line.words)])
            # 1) value to the right on the same line, before the next label and within a reasonable gap
            right = [w for w in line.words[b:nxt] if w.x0 - line.words[b - 1].x1 < 160]
            if right:
                value = _valid(field, " ".join(w.text for w in right))
                if value is not None:
                    found[field] = _field(value, right, 0.95, f"label right: {line.words[a].text}")
                    continue
            # 2) value in the box under the label (boxed headers): bounded by whatever word comes next on
            #    the label's line, which in a row of boxes is the next box's label
            label_x0 = line.words[a].x0
            limit = line.words[b].x0 if b < len(line.words) else label_x0 + 200
            for below in lines[idx + 1 : idx + 3]:
                if below.page != line.page or below.top - line.top > 30:
                    break
                under = [w for w in below.words if label_x0 - 4 <= w.x0 < limit - 2]
                value = _valid(field, " ".join(w.text for w in under)) if under else None
                if value is not None:
                    found[field] = _field(value, under, 0.9, f"label above: {line.words[a].text}")
                    break
    if kind == "customer_po":
        _fallbacks(lines, found, stop_top)
    return found


NUMBER_LABEL = re.compile(r"^(no\.?|number|#|ref\.?|reference)$", re.IGNORECASE)


def _header_lines(lines: list[TextLine], stop_top) -> list[TextLine]:
    return [ln for ln in lines if not stop_top or (ln.page, ln.top) < stop_top]


def _fallbacks(lines: list[TextLine], found: dict, stop_top) -> None:
    """Version 1.1: when the label is not one we know, use rules that hold for any purchase order.
    Values found this way get low confidence, so the intake screen sends a person to them first."""
    head = _header_lines(lines, stop_top)
    if "po_number" not in found:
        for line in head:
            for k, w in enumerate(line.words[:-1]):
                # "... No." / "... Number" / "... Ref" followed by an identifier; not our own documents' numbers
                if NUMBER_LABEL.match(w.text) and k <= 3:
                    value = _valid("po_number", line.words[k + 1].text)
                    if value and not TRN.fullmatch(value) and not OUR_PO.fullmatch(value):
                        found["po_number"] = _field(
                            value, [line.words[k + 1]], 0.6, f"generic number label: {w.text}"
                        )
                        break
            if "po_number" in found:
                break
    missing = [f for f in ("po_date", "required_by") if f not in found]
    if missing:
        dates: list[tuple] = []
        for line in head:
            ws = line.words
            k = 0
            while k < len(ws):
                for n in (3, 2, 1):  # dates can be one to three words ("October 18, 2026")
                    if k + n <= len(ws):
                        d = parse_date(" ".join(w.text for w in ws[k : k + n]))
                        if d:
                            dates.append((d, ws[k : k + n]))
                            k += n
                            break
                else:
                    k += 1
        known = {found[f]["value"] for f in ("po_date", "required_by") if f in found}
        free = sorted({d: w for d, w in dates if d not in known}.items())
        if "po_date" in missing and free:
            d, ws = free[0]
            found["po_date"] = _field(d, ws, 0.5, "date order: the earliest date in the header")
            free = free[1:]
        if "required_by" in missing and free:
            d, ws = free[-1]
            found["required_by"] = _field(d, ws, 0.5, "date order: the latest date in the header")


# ---------------------------------------------------------------- line-item table


def _column_spans(line: TextLine) -> dict[str, tuple[float, float]] | None:
    """Recognise a row of column headings; return role -> (x0, x1) of the heading."""
    phrases = sorted(
        ((role, h) for role, hs in COLUMNS.items() for h in hs), key=lambda rh: -len(rh[1].split())
    )
    toks = [w.text.lower() for w in line.words]
    found: dict[str, tuple[float, float]] = {}
    matched_text: dict[str, str] = {}
    i = 0
    while i < len(toks):
        for role, h in phrases:
            n = len(h.split())
            if " ".join(toks[i : i + n]) == h:
                span = (line.words[i].x0, line.words[i + n - 1].x1)
                if role == "part_number" and "part_number" in found:
                    # two part-like headings ("Item" and "SKU"): the more specific one is the part column,
                    # the other is the line number
                    old = matched_text["part_number"]
                    if PART_PRIORITY.index(h) < PART_PRIORITY.index(old):
                        found["line_no"], found["part_number"] = found["part_number"], span
                        matched_text["part_number"] = h
                    else:
                        found.setdefault("line_no", span)
                elif role not in found:
                    found[role] = span
                    matched_text[role] = h
                i += n
                break
        else:
            i += 1
    roles = set(found)
    if "part_number" in roles and len(roles & {"qty", "unit_price", "amount", "description", "serials"}) >= 2:
        return found
    return None


def _assign(word: Word, cols: dict[str, tuple[float, float]]) -> str | None:
    """Which column a word belongs to: numbers by their right edge, text by its left edge."""
    numeric = parse_money(word.text) is not None or parse_int(word.text) is not None
    if numeric:
        # Figures line up with their heading: right edges for right-aligned columns, left edges otherwise.
        # A number elsewhere ("1 year" inside a description) is text.
        best, dist = None, 9999.0
        for role in ("qty", "unit_price", "amount", "line_no"):
            if role in cols:
                x0, x1 = cols[role]
                d = min(abs(word.x1 - x1), abs(word.x0 - x0))
                if d < dist:
                    best, dist = role, d
        if best and dist < 14:
            return best
    starts = sorted(((x0, role) for role, (x0, _x1) in cols.items()), key=lambda t: t[0])
    owner = None
    for x0, role in starts:
        if word.x0 >= x0 - 6:
            owner = role
    return owner


def _is_stop(line: TextLine, cols) -> bool:
    low = line.text.lower()
    if any(low.startswith(s) or s in low for s in STOP_WORDS):
        return True
    # Money on a line with no part number is not an item: it is the totals block under the table.
    # (Wrapped descriptions and serial lists carry no money, so they stay with their item.)
    # Only money that lines up with a price or amount column counts ("1.92 TB" in a description does not).
    has_money = any(
        parse_money(w.text) is not None and _assign(w, cols) in ("unit_price", "amount") for w in line.words
    )
    has_part = any(PART.match(w.text) and _assign(w, cols) == "part_number" for w in line.words)
    return has_money and not has_part


def table(lines: list[TextLine]) -> tuple[list[dict], int | None, tuple[int, float] | None]:
    """Line items, the index of the first line after the table, and the (page, top) of the heading row."""
    start = None
    cols = None
    for i, line in enumerate(lines):
        cols = _column_spans(line)
        if cols:
            start = i
            break
    if start is None:
        return [], None, None
    heading = (lines[start].page, lines[start].top)
    rows: list[dict] = []
    end = len(lines)
    last_top = lines[start].top
    for j in range(start + 1, len(lines)):
        line = lines[j]
        if line.page != lines[start].page or line.top - last_top > 70 or _is_stop(line, cols):
            end = j
            break
        last_top = line.top
        cells: dict[str, list[Word]] = {}
        for w in line.words:
            role = _assign(w, cols)
            if role:
                cells.setdefault(role, []).append(w)
        part_words = [w for w in cells.get("part_number", []) if PART.match(w.text)]
        if part_words:
            rows.append({"cells": cells, "part": part_words[0]})
        elif rows:
            for role in ("description", "serials", "remarks", "part_number"):
                for w in cells.get(role, []):
                    rows[-1]["cells"].setdefault("description" if role == "part_number" else role, []).append(
                        w
                    )
    items = []
    for n, row in enumerate(rows, start=1):
        c = row["cells"]
        item: dict = {
            "line_no": n,
            "part_number": _field(row["part"].text, [row["part"]], 0.95, "part column"),
        }
        desc = [w for w in c.get("description", [])]
        if desc:
            item["description"] = _field(" ".join(w.text for w in desc), desc, 0.9, "description column")
        for role, parse in (("qty", parse_int), ("unit_price", parse_money), ("amount", parse_money)):
            ws = c.get(role, [])
            vals = [(parse(w.text), w) for w in ws if parse(w.text) is not None]
            if vals:
                item[role] = _field(vals[0][0], [vals[0][1]], 0.9, f"{role} column")
        serial_words = [w for w in c.get("serials", []) if w.text.lower() not in ("not", "serialised")]
        if "serials" in c:
            serials = [s for w in serial_words for s in re.split(r"[,\s]+", w.text) if s]
            item["serials"] = _field(serials, serial_words or None, 0.9, "serial column")
        sub_text = " ".join(w.text for w in c.get("description", []) + c.get("remarks", []))
        m = SUBSTITUTE.search(sub_text)
        if m:
            item["substitutes_part"] = _field(m.group(1).rstrip(")"), None, 0.9, "replaces / sub for")
        _cross_check(item)
        items.append(item)
    return items, end, heading


def _cross_check(item: dict) -> None:
    """Qty x price = amount raises confidence; a missing amount is computed; a mismatch lowers confidence."""
    q, p, a = (item.get(k, {}).get("value") for k in ("qty", "unit_price", "amount"))
    if q is not None and p is not None and a is not None:
        ok = (Decimal(q) * p).quantize(Decimal("0.01")) == a
        for k in ("qty", "unit_price", "amount"):
            item[k]["confidence"] = 0.99 if ok else 0.5
        if not ok:
            item["warning"] = "quantity x unit price does not equal the line amount"
    elif q is not None and p is not None:
        item["amount"] = _field(
            (Decimal(q) * p).quantize(Decimal("0.01")), None, 0.7, "computed: qty x price"
        )


# ---------------------------------------------------------------- totals


def totals(lines: list[TextLine], after: int | None) -> dict:
    if after is None:
        return {}
    found: dict[str, dict] = {}
    unlabelled: list[tuple[Decimal, Word]] = []
    for line in lines[after : after + 8]:
        money = [(parse_money(w.text), w) for w in line.words if parse_money(w.text) is not None]
        if not money:
            continue
        value, word = money[-1]
        label = " ".join(w.text.lower() for w in line.words if parse_money(w.text) is None)
        for field in (
            "vat",
            "subtotal",
            "total",
        ):  # VAT first: "VAT 5%"; then "Total Net Value" is a subtotal
            if any(k in label for k in TOTAL_WORDS[field]) and field not in found:
                found[field] = _field(value, [word], 0.95, f"totals label: {label.strip()}")
                break
        else:
            unlabelled.append((value, word))
    # Labels not recognised: three amounts stacked under the table read as subtotal, VAT, total.
    if not found and len(unlabelled) == 3:
        for field, (value, word) in zip(("subtotal", "vat", "total"), unlabelled, strict=True):
            found[field] = _field(value, [word], 0.6, "position: amounts under the table")
    return {("vat_amount" if k == "vat" else k): v for k, v in found.items()}


# ---------------------------------------------------------------- the document


def extract_pdf(pdf_bytes: bytes, kind: str | None = None) -> dict:
    lines, sizes = read_lines(pdf_bytes)
    kind = kind or classify(lines)
    items, after, heading = table(lines)
    fields = header_fields(lines, kind, heading)
    if kind == "customer_po":
        fields.update(totals(lines, after))
        for line in lines:
            for w in line.words:
                m = TRN.search(w.text)
                if m and m.group(0) != OUR_TRN and "buyer_trn" not in fields:
                    fields["buyer_trn"] = _field(m.group(0), [w], 0.9, "TRN that is not ours")
    if kind == "delivery_note":
        text = " ".join(line.text.lower() for line in lines)
        partial = "part delivery" in text or "balance to follow" in text
        fields["marked_partial"] = _field(partial, None, 0.9, "words: part delivery / balance to follow")
    warnings = []
    if len(sizes) > 1:
        warnings.append(
            "Multipage PDF: extraction is incomplete. Check every page and add any missing lines."
        )
    missing = [f for f in HEADER_FIELDS[kind] if f not in fields]
    if missing:
        warnings.append("not found: " + ", ".join(missing))
    if not items:
        warnings.append("no line-item table found")
    return {
        "kind": kind,
        "extractor_version": EXTRACTOR_VERSION,
        "fields": fields,
        "lines": items,
        "page_sizes": sizes,
        "warnings": warnings,
    }
