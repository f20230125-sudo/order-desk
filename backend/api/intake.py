"""Adding a document: upload it, see what was read (with where on the page it came from), correct, confirm.

Nothing is written to the order until a person confirms. The upload waits in pending_upload (the app runs
on serverless instances that share no disk), and the same file is never taken twice.
"""

import hashlib
import json
from collections import Counter

import psycopg
from flask import Blueprint, Response, jsonify, request
from pydantic import ValidationError

from backend.api.common import acting_role, check_daily_upload_cap, db, limit_writes
from backend.config import MAX_UPLOAD_BYTES
from backend.db.conn import write_tx
from backend.errors import ApiError
from backend.extract.detect import extract, sniff
from backend.models import CONFIRM_MODELS
from backend.orders import run_checks

bp = Blueprint("intake", __name__)
KINDS = ("customer_po", "vendor_confirmation", "delivery_note", "shipment_email")


def _json(obj) -> psycopg.types.json.Jsonb:
    return psycopg.types.json.Jsonb(obj, dumps=lambda o: json.dumps(o, default=str))


def _suggest(conn, kind: str, extracted: dict) -> dict:
    """Which customer or order the document probably belongs to, from what it says."""
    f = extracted.get("fields", {})
    if kind == "customer_po":
        trn = (f.get("buyer_trn") or {}).get("value")
        cust = (
            conn.execute("select id, name from party where kind = 'customer' and trn = %s", (trn,)).fetchone()
            if trn
            else None
        )
        return {"customer": cust}
    ref = (f.get("referenced_po") or {}).get("value")
    order = (
        conn.execute(
            """select co.id, co.po_number, p.name as customer_name, po.our_po_number from purchase_order po
           join customer_order co on co.id = po.customer_order_id join party p on p.id = co.customer_id
           where upper(po.our_po_number) = upper(%s)""",
            (ref,),
        ).fetchone()
        if ref
        else None
    )
    return {"order": order}


@bp.post("/api/intake")
def upload():
    role = acting_role()
    limit_writes(cost=3)
    file = request.files.get("file")
    if file is None:
        raise ApiError(400, "file_required", "Attach a PDF or an email (.eml) file.")
    data = file.read(MAX_UPLOAD_BYTES + 1)
    if not data:
        raise ApiError(400, "empty_file", "That file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ApiError(413, "file_too_large", "Files up to 2 MB only.")
    mime = sniff(data)
    if mime is None:
        raise ApiError(
            415,
            "unsupported_file",
            "Only PDF documents and .eml emails can be read. Outlook .msg "
            "files are not supported yet: save the email as .eml instead.",
        )
    kind = request.form.get("kind") or None
    if kind and kind not in KINDS:
        raise ApiError(400, "bad_kind", f"kind must be one of {', '.join(KINDS)}")
    conn = db()
    digest = hashlib.sha256(data).hexdigest()
    seen = conn.execute(
        "select id, customer_order_id, uploaded_at, filename from document where sha256 = %s", (digest,)
    ).fetchone()
    if seen:
        raise ApiError(
            409,
            "already_received",
            f"This file was already added on {seen['uploaded_at']:%d %b %Y}.",
            details={
                "document_id": seen["id"],
                "order_id": seen["customer_order_id"],
                "filename": seen["filename"],
            },
        )
    try:
        _mime, extracted = extract(data, kind)
    except Exception as exc:  # a damaged or unusual file: say so instead of failing the request
        raise ApiError(
            422,
            "unreadable",
            "The file could not be read. Is it a scanned image? Scans need OCR, which this demo does not do.",
        ) from exc
    kind = extracted["kind"]
    filename = (file.filename or "document")[:120]
    with write_tx(conn, role):
        check_daily_upload_cap(len(data))
        conn.execute("delete from pending_upload where expires_at < now()")
        pending = conn.execute(
            """insert into pending_upload (kind, filename, mime, sha256, size_bytes, content, extracted)
               values (%s, %s, %s, %s, %s, %s, %s) returning id, expires_at""",
            (kind, filename, mime, digest, len(data), data, _json(extracted)),
        ).fetchone()
    return jsonify(
        pending_id=pending["id"],
        expires_at=pending["expires_at"],
        kind=kind,
        mime=mime,
        filename=filename,
        extracted=extracted,
        suggestion=_suggest(conn, kind, extracted),
    ), 201


@bp.get("/api/intake/<uuid:pending_id>/file")
def pending_file(pending_id):
    row = (
        db()
        .execute(
            "select mime, content from pending_upload where id = %s and expires_at > now()", (pending_id,)
        )
        .fetchone()
    )
    if row is None:
        raise ApiError(404, "upload_expired", "This upload has expired. Add the file again.")
    return Response(
        bytes(row["content"]),
        mimetype=row["mime"],
        headers={
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; sandbox",
        },
    )


@bp.post("/api/intake/<uuid:pending_id>/confirm")
def confirm(pending_id):
    role = acting_role()
    limit_writes()
    conn = db()
    pending = conn.execute(
        "select * from pending_upload where id = %s and expires_at > now()", (pending_id,)
    ).fetchone()
    if pending is None:
        raise ApiError(404, "upload_expired", "This upload has expired. Add the file again.")
    body = request.get_json(silent=True) or {}
    body["kind"] = pending["kind"]
    try:
        data = CONFIRM_MODELS[pending["kind"]].model_validate(body)
    except ValidationError as exc:
        problems = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        raise ApiError(
            400, "check_the_form", "Some values need a look before saving.", details=problems
        ) from exc

    with write_tx(conn, role):
        if data.kind == "customer_po":
            order_id = _save_customer_po(conn, data)
        elif data.kind == "vendor_confirmation":
            order_id = _save_confirmation(conn, data)
        else:
            order_id = _save_goods_in(conn, data)
        conn.execute(
            """insert into document (kind, filename, mime, sha256, size_bytes, content, extracted, extractor_version,
                   customer_order_id, uploaded_by_role)
               select kind, filename, mime, sha256, size_bytes, content, extracted, extracted ->> 'extractor_version',
                      %s, %s from pending_upload where id = %s""",
            (order_id, role, pending_id),
        )
        conn.execute("delete from pending_upload where id = %s", (pending_id,))
        result = run_checks(conn, order_id, role)
    return jsonify(ok=True, order_id=order_id, check=result), 201


def _description(conn, part: str, given: str) -> str:
    if given:
        return given
    row = conn.execute("select description from product where part_number = %s", (part,)).fetchone()
    return row["description"] if row else part


def _save_customer_po(conn, d) -> int:
    if not conn.execute(
        "select 1 from party where id = %s and kind = 'customer'", (d.customer_id,)
    ).fetchone():
        raise ApiError(400, "customer_required", "Choose which customer sent this PO.")
    if conn.execute(
        "select 1 from customer_order where customer_id = %s and po_number = %s", (d.customer_id, d.po_number)
    ).fetchone():
        raise ApiError(409, "po_exists", f"PO {d.po_number} from this customer is already on the board.")
    order_id = conn.execute(
        """insert into customer_order (po_number, customer_id, po_date, required_by, subtotal, vat_amount, total)
           values (%s, %s, %s, %s, %s, %s, %s) returning id""",
        (d.po_number, d.customer_id, d.po_date, d.required_by, d.subtotal, d.vat_amount, d.total),
    ).fetchone()["id"]
    for n, ln in enumerate(d.lines, start=1):
        conn.execute(
            "insert into customer_order_line (order_id, line_no, part_number, description, qty, unit_price) "
            "values (%s, %s, %s, %s, %s, %s)",
            (
                order_id,
                n,
                ln.part_number,
                _description(conn, ln.part_number, ln.description),
                ln.qty,
                ln.unit_price,
            ),
        )
    return order_id


def _order_po(conn, order_id: int) -> dict:
    po = conn.execute("select id from purchase_order where customer_order_id = %s", (order_id,)).fetchone()
    if po is None:
        raise ApiError(
            409,
            "no_po_yet",
            "Our PO for this order has not gone out yet, so there is nothing to confirm or receive against.",
        )
    return po


def _save_confirmation(conn, d) -> int:
    po = _order_po(conn, d.order_id)
    if conn.execute(
        "select 1 from vendor_confirmation where po_id = %s and confirmation_no = %s",
        (po["id"], d.confirmation_no),
    ).fetchone():
        raise ApiError(
            409, "confirmation_exists", f"Confirmation {d.confirmation_no} is already on this order."
        )
    conf_id = conn.execute(
        "insert into vendor_confirmation (po_id, confirmation_no, referenced_po, eta) "
        "values (%s, %s, %s, %s) returning id",
        (po["id"], d.confirmation_no, d.referenced_po, d.eta),
    ).fetchone()["id"]
    for n, ln in enumerate(d.lines, start=1):
        conn.execute(
            "insert into vendor_confirmation_line (confirmation_id, line_no, part_number, description, qty, "
            "unit_cost, substitutes_part) values (%s, %s, %s, %s, %s, %s, %s)",
            (
                conf_id,
                n,
                ln.part_number,
                _description(conn, ln.part_number, ln.description),
                ln.qty,
                ln.unit_price,
                ln.substitutes_part,
            ),
        )
    return d.order_id


def _save_goods_in(conn, d) -> int:
    po = _order_po(conn, d.order_id)
    # A dispatch email and the delivery note describe the same delivery: the second one fills in, not adds.
    existing = conn.execute(
        "select id from shipment where customer_order_id = %s and direction = 'inbound' "
        "and delivery_note_no = %s",
        (d.order_id, d.delivery_note_no),
    ).fetchone()
    if existing:
        ship_id = existing["id"]
        stored = conn.execute(
            "select part_number, sum(qty) as qty from shipment_line where shipment_id = %s group by part_number",
            (ship_id,),
        ).fetchall()
        quantities = Counter()
        for ln in d.lines:
            quantities[ln.part_number] += ln.qty
        if quantities != Counter({r["part_number"]: r["qty"] for r in stored}):
            raise ApiError(
                409,
                "delivery_conflict",
                "This delivery is already recorded with different parts or quantities. Check both documents.",
            )
        conn.execute(
            "update shipment set tracking_number = coalesce(tracking_number, %s), "
            "marked_partial = marked_partial or %s where id = %s",
            (d.tracking_number, d.marked_partial, ship_id),
        )
        for ln in d.lines:
            row = conn.execute(
                "select id, serials_as_documented from shipment_line where shipment_id = %s "
                "and part_number = %s",
                (ship_id, ln.part_number),
            ).fetchone()
            if row and not row["serials_as_documented"] and ln.serials:
                conn.execute(
                    "update shipment_line set serials_as_documented = %s where id = %s",
                    (ln.serials, row["id"]),
                )
                _book_serials(conn, row["id"], ln.serials)
        return d.order_id
    ship_id = conn.execute(
        """insert into shipment (direction, customer_order_id, po_id, tracking_number, delivery_note_no, shipped_at,
               received_at, marked_partial) values ('inbound', %s, %s, %s, %s, now(), now(), %s) returning id""",
        (d.order_id, po["id"], d.tracking_number, d.delivery_note_no, d.marked_partial),
    ).fetchone()["id"]
    for ln in d.lines:
        line_id = conn.execute(
            "insert into shipment_line (shipment_id, part_number, qty, serials_as_documented) "
            "values (%s, %s, %s, %s) returning id",
            (ship_id, ln.part_number, ln.qty, ln.serials),
        ).fetchone()["id"]
        _book_serials(conn, line_id, ln.serials)
    return d.order_id


def _book_serials(conn, line_id: int, serials: list[str]) -> None:
    # A serial already booked in elsewhere stays on the paper (serials_as_documented) and is flagged by the
    # check; the database itself refuses to book the same unit twice.
    for s in dict.fromkeys(serials):
        conn.execute(
            "insert into serial (shipment_line_id, serial_no, direction) values (%s, %s, 'inbound') "
            "on conflict (serial_no, direction) do nothing",
            (line_id, s),
        )
