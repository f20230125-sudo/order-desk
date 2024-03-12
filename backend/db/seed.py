"""Fill the database with the synthetic orders, replaying each order's history step by step.

    python -m backend.db.seed --reset           # DATABASE_URL_UNPOOLED (the demo database)
    python -m backend.db.seed --reset --test    # DATABASE_URL_TEST

Each step runs as the role that would do it (sales books the customer PO, ops places and receives, finance
takes it over) at the time it would have happened, so the audit log tells a believable story and the
board's "days waiting" are real. Documents are rendered, read back by the extractor and stored, and the
checks run after every step, exactly as they would for documents uploaded through the app.

--reset empties every table first, in one transaction with the reload, so the live demo never shows a
half-empty database. It refuses to run against a host that is not named in ORDER_DESK_RESET_HOST, unless
the target is the local test database.
"""

import hashlib
import os
import random
import sys
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlparse

import psycopg

from backend.config import database_url
from backend.db.conn import connect, write_tx
from backend.db.migrate import migrate
from backend.extract.detect import extract
from backend.orders import run_checks
from synth.catalogue import CARRIERS, CUSTOMERS, DISTRIBUTORS, PRODUCT_BY_PART
from synth.generate import documents_for
from synth.scenario import STAGES, SynthOrder, build

TABLES = (
    "event, rate_limit, pending_upload, discrepancy, check_run, document, serial, shipment_line, shipment, "
    "vendor_confirmation_line, vendor_confirmation, purchase_order_line, purchase_order, "
    "customer_order_line, customer_order, product, party"
)

# How an earlier problem was settled on an order that has since moved on: (status, role, note).
RESOLUTIONS = {
    "VAT_MATH": (
        "fixed",
        "sales",
        "Customer reissued the PO with VAT at 5%. Their finance team confirmed by email.",
    ),
    "TOTAL_MATH": (
        "fixed",
        "sales",
        "Customer confirmed the line amounts; the printed total was a typing error.",
    ),
    "PART_MISMATCH": (
        "accepted",
        "sales",
        "Customer agreed to take the model we ordered. Same specification, confirmed by their IT manager.",
    ),
    "QTY_SHORT": ("accepted", "ops", "Balance placed on a follow-up PO; customer told the date."),
    "PRICE_DIFF": (
        "accepted",
        "sales",
        "Distributor price rise accepted after review. Margin still above the floor.",
    ),
    "SUBSTITUTION": ("accepted", "sales", "Customer approved the substitute part in writing."),
    "MISSING_LINE": ("accepted", "ops", "Missing line re-ordered and confirmed separately."),
    "EXTRA_LINE": ("fixed", "ops", "Distributor removed the extra line and sent a revised confirmation."),
    "PO_REF": ("fixed", "ops", "Distributor confirmed it is our PO and sent a corrected confirmation."),
    "ETA_LATE": ("accepted", "sales", "Customer agreed to the later delivery date."),
    "QTY_OVER": ("accepted", "ops", "Extra units returned to the distributor; return note filed."),
    "SERIAL_COUNT": ("fixed", "ops", "Missing serial read from the unit label at goods-in and added."),
    "DUPLICATE_SERIAL": (
        "fixed",
        "ops",
        "Label misprint: the real serial was read from the unit and booked in.",
    ),
    "PARTIAL_SHIPMENT": ("fixed", "ops", "Balance arrived; delivery complete."),
}


def _at(now: datetime, days_ago: int, rng: random.Random) -> datetime:
    t = (now - timedelta(days=days_ago)).replace(
        hour=rng.randint(8, 16), minute=rng.randint(0, 59), second=0, microsecond=0
    )
    return min(t, now - timedelta(minutes=rng.randint(20, 90)))


def _document(conn, kind: str, name: str, data: bytes, order_id: int, role: str) -> None:
    mime, extracted = extract(data, kind)
    conn.execute(
        """insert into document (kind, filename, mime, sha256, size_bytes, content, extracted, extractor_version,
               customer_order_id, uploaded_by_role)
           values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (
            kind,
            name,
            mime,
            hashlib.sha256(data).hexdigest(),
            len(data),
            data,
            psycopg.types.json.Jsonb(extracted, dumps=_dumps),
            extracted["extractor_version"],
            order_id,
            role,
        ),
    )


def _dumps(obj) -> str:
    import json

    return json.dumps(obj, default=str)


def _parties(conn) -> dict[str, int]:
    ids = {}
    for p in CUSTOMERS + DISTRIBUTORS + CARRIERS:
        ids[p.short_code] = conn.execute(
            "insert into party (kind, name, short_code, trn, sector, address, emirate) "
            "values (%s, %s, %s, %s, %s, %s, %s) returning id",
            (p.kind, p.name, p.short_code, p.trn, p.sector, p.address, p.emirate),
        ).fetchone()["id"]
    for prod in PRODUCT_BY_PART.values():
        conn.execute(
            "insert into product (part_number, brand, description, category, serialised, list_price) "
            "values (%s, %s, %s, %s, %s, %s)",
            (prod.part_number, prod.brand, prod.description, prod.category, prod.serialised, prod.list_price),
        )
    return ids


def _seed_order(conn, o: SynthOrder, ids: dict[str, int], now: datetime, rng: random.Random) -> int:
    docs = {t["kind"]: (name, data) for name, data, t in documents_for(o)}
    reached = STAGES.index(o.stage)
    t0 = _at(now, o.days_ago["po_received"], rng)
    po = o.customer_po

    with write_tx(conn, "sales", at=t0):
        order_id = conn.execute(
            """insert into customer_order (po_number, customer_id, po_date, received_at, required_by, subtotal,
                   vat_amount, total, deliver_to, contact_name)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
            (
                po.po_number,
                ids[o.customer.short_code],
                po.po_date,
                t0,
                po.required_by,
                po.subtotal,
                po.vat_amount,
                po.total,
                o.deliver_to,
                o.contact,
            ),
        ).fetchone()["id"]
        for ln in po.lines:
            conn.execute(
                "insert into customer_order_line (order_id, line_no, part_number, description, qty, unit_price) "
                "values (%s, %s, %s, %s, %s, %s)",
                (order_id, ln.line_no, ln.part_number, ln.description, ln.qty, ln.unit_price),
            )
        _document(conn, "customer_po", *docs["customer_po"], order_id, "sales")
        run_checks(conn, order_id, "sales", at=t0)

    if reached >= 1:
        t1 = max(t0 + timedelta(hours=2), _at(now, o.days_ago["po_sent"], rng))
        with write_tx(conn, "ops", at=t1):
            po_id = conn.execute(
                "insert into purchase_order (our_po_number, customer_order_id, distributor_id, sent_at) "
                "values (%s, %s, %s, %s) returning id",
                (o.our_po.our_po_number, order_id, ids[o.distributor.short_code], t1),
            ).fetchone()["id"]
            for ln in o.our_po.lines:
                conn.execute(
                    "insert into purchase_order_line (po_id, line_no, part_number, description, qty, unit_cost) "
                    "values (%s, %s, %s, %s, %s, %s)",
                    (po_id, ln.line_no, ln.part_number, ln.description, ln.qty, ln.unit_price),
                )
            run_checks(conn, order_id, "ops", at=t1)

    if o.confirmation:
        t2 = max(t1 + timedelta(hours=3), _at(now, o.days_ago["confirmed"], rng))
        c = o.confirmation
        with write_tx(conn, "ops", at=t2):
            conf_id = conn.execute(
                "insert into vendor_confirmation (po_id, confirmation_no, confirmed_at, referenced_po, eta) "
                "values (%s, %s, %s, %s, %s) returning id",
                (po_id, c.confirmation_no, t2, c.referenced_po, c.eta),
            ).fetchone()["id"]
            for ln in c.lines:
                conn.execute(
                    "insert into vendor_confirmation_line (confirmation_id, line_no, part_number, description, qty, "
                    "unit_cost, substitutes_part) values (%s, %s, %s, %s, %s, %s, %s)",
                    (
                        conf_id,
                        ln.line_no,
                        ln.part_number,
                        ln.description,
                        ln.qty,
                        ln.unit_price,
                        ln.substitutes_part,
                    ),
                )
            _document(conn, "vendor_confirmation", *docs["vendor_confirmation"], order_id, "ops")
            run_checks(conn, order_id, "ops", at=t2)

    for ship in o.inbound:
        if "received" in o.days_ago:
            t3 = max(t2 + timedelta(hours=4), _at(now, o.days_ago["received"], rng))
        else:  # a part delivery or a short one on an order still open at "confirmed"
            t3 = min(now - timedelta(hours=3), t2 + timedelta(days=rng.randint(1, 2)))
        with write_tx(conn, "ops", at=t3):
            ship_id = conn.execute(
                """insert into shipment (direction, customer_order_id, po_id, carrier_id, tracking_number,
                       delivery_note_no, shipped_at, received_at, marked_partial)
                   values ('inbound', %s, %s, %s, %s, %s, %s, %s, %s) returning id""",
                (
                    order_id,
                    po_id,
                    ids[o.carrier.short_code],
                    o.tracking[ship.reference],
                    ship.reference,
                    t3 - timedelta(days=1),
                    t3,
                    ship.marked_partial,
                ),
            ).fetchone()["id"]
            for sl in ship.lines:
                line_id = conn.execute(
                    "insert into shipment_line (shipment_id, part_number, qty, serials_as_documented) "
                    "values (%s, %s, %s, %s) returning id",
                    (ship_id, sl.part_number, sl.qty, sl.serials),
                ).fetchone()["id"]
                for serial in dict.fromkeys(sl.serials):
                    conn.execute(
                        "insert into serial (shipment_line_id, serial_no, direction) values (%s, %s, 'inbound') "
                        "on conflict (serial_no, direction) do nothing",
                        (line_id, serial),
                    )
            _document(conn, "delivery_note", *docs["delivery_note"], order_id, "ops")
            _document(conn, "shipment_email", *docs["shipment_email"], order_id, "ops")
            run_checks(conn, order_id, "ops", at=t3)

    for ship in o.outbound:
        t4 = max(t3 + timedelta(hours=5), _at(now, o.days_ago["delivered"], rng))
        with write_tx(conn, "ops", at=t4):
            ship_id = conn.execute(
                """insert into shipment (direction, customer_order_id, carrier_id, delivery_note_no, shipped_at,
                       received_at) values ('outbound', %s, %s, %s, %s, %s) returning id""",
                (order_id, ids[o.carrier.short_code], ship.reference, t4 - timedelta(hours=4), t4),
            ).fetchone()["id"]
            for sl in ship.lines:
                line_id = conn.execute(
                    "insert into shipment_line (shipment_id, part_number, qty, serials_as_documented) "
                    "values (%s, %s, %s, %s) returning id",
                    (ship_id, sl.part_number, sl.qty, sl.serials),
                ).fetchone()["id"]
                for serial in dict.fromkeys(sl.serials):
                    conn.execute(
                        "insert into serial (shipment_line_id, serial_no, direction) values (%s, %s, 'outbound') "
                        "on conflict (serial_no, direction) do nothing",
                        (line_id, serial),
                    )
            run_checks(conn, order_id, "ops", at=t4)

    # Problems from earlier links of the chain, on orders that have since moved on, were settled on the way.
    if reached >= 3:
        settle = _at(now, max(0, o.days_ago[o.stage]), rng)
        for d in conn.execute(
            "select id, code, stage from discrepancy where customer_order_id = %s and status = 'open'",
            (order_id,),
        ).fetchall():
            if STAGES.index(d["stage"]) < reached:
                status, role, note = RESOLUTIONS[d["code"]]
                with write_tx(conn, role, at=settle):
                    conn.execute(
                        "update discrepancy set status = %s, resolution_note = %s, resolved_by_role = %s, "
                        "resolved_at = %s where id = %s",
                        (status, note, role, settle, d["id"]),
                    )

    if o.stage == "ready_to_invoice":
        t5 = _at(now, o.days_ago["ready_to_invoice"], rng)
        with write_tx(conn, "finance", at=t5):
            conn.execute("update customer_order set ready_to_invoice_at = %s where id = %s", (t5, order_id))
    return order_id


def seed(conn: psycopg.Connection, reset: bool = False, today: date | None = None) -> dict:
    """Load the orders. Run migrate() first, outside this transaction (it commits as it goes)."""
    now = datetime.now(UTC)
    today = today or now.date()
    if reset:
        conn.execute(f"truncate {TABLES} restart identity cascade")
    elif conn.execute("select count(*) as n from customer_order").fetchone()["n"]:
        raise SystemExit("the database already has orders; pass --reset to replace them")
    rng = random.Random(41)
    with write_tx(conn, "system"):
        ids = _parties(conn)
    orders = build(today=today)
    for o in orders:
        _seed_order(conn, o, ids, now, rng)
    counts = conn.execute(
        """select (select count(*) from customer_order) as orders, (select count(*) from document) as documents,
                  (select count(*) from discrepancy where status = 'open') as open_problems,
                  (select count(*) from event) as events"""
    ).fetchone()
    return dict(counts)


def _allowed(url: str, test: bool) -> bool:
    host = urlparse(url).hostname or ""
    if test:
        return True
    allowed = os.environ.get("ORDER_DESK_RESET_HOST", "")
    return bool(allowed) and host == allowed


def main() -> None:
    test = "--test" in sys.argv
    reset = "--reset" in sys.argv
    url = database_url("test" if test else "direct")
    if reset and not _allowed(url, test):
        raise SystemExit("refusing to reset: set ORDER_DESK_RESET_HOST to this database's host name first")
    with connect("test" if test else "direct") as conn:
        migrate(conn)
        # One transaction for the whole reload: visitors see the old data or the new, never half of it.
        with conn.transaction():
            counts = seed(conn, reset=reset)
    print(counts)


if __name__ == "__main__":
    main()
