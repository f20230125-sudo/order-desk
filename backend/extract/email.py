"""Read a dispatch email (.eml): tracking number, delivery note, our PO number, the items, and the serial
numbers, whether they are typed in the body or attached as a CSV file.

Tracking numbers are recognised by each carrier's own pattern, so a number in the body is not mistaken for
one. An email has no page to draw on, so fields here carry no box; the screen shows the email text with
the matched words marked instead (the `span` gives character offsets into `text`).
"""

import csv
import io
import re
from email import policy
from email.parser import BytesParser

from backend.extract import EXTRACTOR_VERSION
from backend.extract.fields import OUR_PO, PART

CARRIER_TRACKING = [
    re.compile(r"\bSG\d{10}\b"),  # Swift Gulf Couriers
    re.compile(r"\b\d{3}-\d{8}\b"),  # air waybill: airline prefix + 8 digits
    re.compile(r"\bSLX\d{9}AE\b"),  # Sandline Express
]
DELIVERY_NOTE = re.compile(r"\bDN-[A-Z]{2,5}-\d{4,6}\b")
ITEM_LINE = re.compile(r"^\s*(?P<part>[A-Z0-9][A-Z0-9.\-/]{3,39})\s+qty\s+(?P<qty>\d{1,6})\b", re.MULTILINE)
SERIAL_LINE = re.compile(
    r"^\s*(?P<part>[A-Z0-9][A-Z0-9.\-/]{3,39}):\s*(?P<serials>[A-Z0-9, ]+)$", re.MULTILINE
)


def _field(value, text: str, m: re.Match | None, confidence: float, rule: str) -> dict:
    out = {"value": value, "confidence": confidence, "rule": rule}
    if m:
        out["span"] = [m.start(), m.end()]
    return out


def extract_email(raw: bytes) -> dict:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    subject = str(msg.get("Subject", ""))
    body_part = msg.get_body(preferencelist=("plain",))
    body = body_part.get_content() if body_part else ""
    text = f"Subject: {subject}\n\n{body}"
    fields: dict[str, dict] = {}

    for pattern in CARRIER_TRACKING:
        m = pattern.search(text)
        if m:
            fields["tracking_number"] = _field(m.group(0), text, m, 0.95, "carrier tracking pattern")
            break
    m = DELIVERY_NOTE.search(text)
    if m:
        fields["delivery_note_no"] = _field(m.group(0), text, m, 0.95, "delivery note pattern")
    m = OUR_PO.search(text)
    if m:
        fields["referenced_po"] = _field(m.group(0), text, m, 0.95, "our PO number pattern")
    partial = re.search(r"\bin part\b|balance (?:will|to) follow", text, re.IGNORECASE)
    fields["marked_partial"] = _field(bool(partial), text, partial, 0.9, "words: in part / balance to follow")

    lines: list[dict] = []
    by_part: dict[str, dict] = {}
    for n, m in enumerate(ITEM_LINE.finditer(text), start=1):
        part = m.group("part")
        if not PART.match(part):
            continue
        item = {
            "line_no": n,
            "part_number": _field(part, text, m, 0.95, "item line"),
            "qty": _field(int(m.group("qty")), text, m, 0.95, "item line"),
            "serials": {"value": [], "confidence": 0.9, "rule": "none listed"},
        }
        lines.append(item)
        by_part[part] = item

    for m in SERIAL_LINE.finditer(text):
        item = by_part.get(m.group("part"))
        if item is not None:
            serials = [s for s in re.split(r"[,\s]+", m.group("serials")) if s]
            item["serials"] = _field(serials, text, m, 0.95, "serial list in the body")

    attachments = []
    for part in msg.iter_attachments():
        name = part.get_filename() or "attachment"
        attachments.append(name)
        if name.lower().endswith(".csv"):
            content = part.get_content()
            if isinstance(content, bytes):
                content = content.decode("utf-8", "replace")
            for row in csv.DictReader(io.StringIO(content)):
                p, s = (row.get("part_number") or "").strip(), (row.get("serial_number") or "").strip()
                if p in by_part and s:
                    item = by_part[p]
                    if item["serials"]["rule"] != "serial file attached":
                        item["serials"] = {
                            "value": [],
                            "confidence": 0.95,
                            "rule": "serial file attached",
                            "source": name,
                        }
                    item["serials"]["value"].append(s)

    warnings = []
    for f in ("tracking_number", "referenced_po"):
        if f not in fields:
            warnings.append(f"not found: {f}")
    if not lines:
        warnings.append("no items listed")
    return {
        "kind": "shipment_email",
        "extractor_version": EXTRACTOR_VERSION,
        "fields": fields,
        "lines": lines,
        "text": text,
        "attachments": attachments,
        "warnings": warnings,
        "from": str(msg.get("From", "")),
        "date": str(msg.get("Date", "")),
    }
