"""One order: its chain, the match grid, its problems, documents and history; and the actions that move
it along the chain (place our PO, deliver to the customer, hand to finance, check again)."""

from datetime import UTC, datetime
from decimal import Decimal

from flask import Blueprint, jsonify, request

from backend.api.common import acting_role, db, limit_writes
from backend.db.conn import write_tx
from backend.errors import ApiError
from backend.orders import run_checks

bp = Blueprint("orders", __name__)

STEP_NAMES = {
    "po_received": "Customer PO received",
    "po_sent": "Our PO sent to the distributor",
    "confirmed": "Distributor confirmed",
    "received": "Goods received",
    "delivered": "Delivered to the customer",
    "ready_to_invoice": "Ready to invoice",
}
# Which column of the match grid a problem belongs to, by the link of the chain where it was found.
STAGE_COLUMN = {"po_sent": "ours", "confirmed": "confirmed", "received": "received", "delivered": "delivered"}


def _order_or_404(order_id: int) -> dict:
    row = db().execute("select * from board where id = %s", (order_id,)).fetchone()
    if row is None:
        raise ApiError(404, "no_such_order", f"There is no order {order_id}.")
    return row


def _chain(o: dict) -> list[dict]:
    times = {
        "po_received": o["received_at"],
        "po_sent": o["sent_at"],
        "confirmed": o["confirmed_at"],
        "received": o["last_received_at"] if o["stage_no"] >= 4 else None,
        "delivered": o["last_delivered_at"] if o["stage_no"] >= 5 else None,
        "ready_to_invoice": o["ready_to_invoice_at"],
    }
    steps = []
    for n, (key, name) in enumerate(STEP_NAMES.items(), start=1):
        state = (
            "done"
            if n < o["stage_no"] or (n == o["stage_no"] == 6)
            else ("current" if n == o["stage_no"] else "todo")
        )
        steps.append({"key": key, "name": name, "state": state, "at": times[key]})
    return steps


def _grid(conn, order_id: int, problems: list[dict]) -> list[dict]:
    """One row per part, values side by side along the chain, each cell carrying the problems found on it."""
    rows: dict[str, dict] = {}

    def row(part: str, description: str = "") -> dict:
        if part not in rows:
            rows[part] = {
                "part_number": part,
                "description": description,
                "customer": None,
                "ours": None,
                "confirmed": None,
                "received": None,
                "delivered": None,
                "serials": [],
                "issues": {},
            }
        if description and not rows[part]["description"]:
            rows[part]["description"] = description
        return rows[part]

    for r in conn.execute(
        "select * from customer_order_line where order_id = %s order by line_no", (order_id,)
    ):
        row(r["part_number"], r["description"])["customer"] = {"qty": r["qty"], "price": r["unit_price"]}
    po = conn.execute("select id from purchase_order where customer_order_id = %s", (order_id,)).fetchone()
    if po:
        for r in conn.execute(
            "select * from purchase_order_line where po_id = %s order by line_no", (po["id"],)
        ):
            row(r["part_number"], r["description"])["ours"] = {"qty": r["qty"], "price": r["unit_cost"]}
        conf = conn.execute(
            "select id from vendor_confirmation where po_id = %s order by confirmed_at desc, id desc limit 1",
            (po["id"],),
        ).fetchone()
        if conf:
            for r in conn.execute(
                "select * from vendor_confirmation_line where confirmation_id = %s order by line_no",
                (conf["id"],),
            ):
                # A substitute is shown on the row of the part it replaces.
                key = r["substitutes_part"] or r["part_number"]
                row(key, r["description"])["confirmed"] = {
                    "qty": r["qty"],
                    "price": r["unit_cost"],
                    "part_number": r["part_number"],
                    "substitutes": r["substitutes_part"],
                }
    subs = {
        v["confirmed"]["part_number"]: k
        for k, v in rows.items()
        if v["confirmed"] and v["confirmed"]["substitutes"]
    }
    for r in conn.execute(
        """select s.direction, sl.part_number, sl.qty, sl.serials_as_documented as serials
               from shipment s join shipment_line sl on sl.shipment_id = s.id
               where s.customer_order_id = %s and s.received_at is not null order by s.id, sl.id""",
        (order_id,),
    ):
        target = row(subs.get(r["part_number"], r["part_number"]))
        column = "received" if r["direction"] == "inbound" else "delivered"
        target[column] = {"qty": (target[column] or {"qty": 0})["qty"] + r["qty"]}
        if r["direction"] == "inbound":
            target["serials"] += list(r["serials"])
    for p in problems:
        if p["part_number"] and p["part_number"] in rows:
            column = STAGE_COLUMN.get(p["stage"], "customer")
            rows[p["part_number"]]["issues"].setdefault(column, []).append(p["id"])
    return list(rows.values())


def _events(conn, order_id: int) -> list[dict]:
    out = []
    for e in conn.execute("select * from event where customer_order_id = %s order by at, id", (order_id,)):
        a, b = e["after"] or {}, e["before"] or {}
        t, action = e["table_name"], e["action"]
        text = None
        if t == "customer_order" and action == "insert":
            text = f"Customer PO {a.get('po_number')} booked"
        elif (
            t == "customer_order"
            and action == "update"
            and a.get("ready_to_invoice_at")
            and not b.get("ready_to_invoice_at")
        ):
            text = "Handed to finance for invoicing"
        elif t == "purchase_order" and action == "insert":
            text = f"Our PO {a.get('our_po_number')} sent to the distributor"
        elif t == "vendor_confirmation" and action == "insert":
            text = f"Distributor confirmation {a.get('confirmation_no')} recorded"
        elif t == "shipment" and action == "insert":
            ref = a.get("delivery_note_no") or a.get("tracking_number") or ""
            text = (
                f"Goods booked in from delivery note {ref}"
                if a.get("direction") == "inbound"
                else f"Delivered to the customer on {ref}"
            )
        elif t == "document" and action == "insert":
            text = f"Document added: {a.get('filename')}"
        elif t == "discrepancy" and action == "insert":
            text = f"Check found: {a.get('explanation')}"
        elif t == "discrepancy" and action == "update" and a.get("status") != b.get("status"):
            text = f"Marked {a.get('status')}: {a.get('resolution_note')}"
        if text:
            out.append({"at": e["at"], "role": e["actor_role"], "text": text, "table": t})
    return out


@bp.get("/api/orders/<int:order_id>")
def order_detail(order_id: int):
    conn = db()
    o = _order_or_404(order_id)
    full = conn.execute("select * from order_chain where id = %s", (order_id,)).fetchone()
    co = conn.execute(
        "select deliver_to, contact_name, po_date, subtotal, vat_amount, vat_rate from customer_order "
        "where id = %s",
        (order_id,),
    ).fetchone()
    problems = conn.execute(
        """select id, code, severity, stage, part_number, expected, found, explanation, status, resolution_note,
                  resolved_by_role, resolved_at from discrepancy where customer_order_id = %s
           order by status = 'open' desc, (severity = 'block') desc, (severity = 'warn') desc, id""",
        (order_id,),
    ).fetchall()
    documents = conn.execute(
        """select id, kind, filename, mime, size_bytes, uploaded_by_role, uploaded_at,
                  jsonb_array_length(coalesce(extracted -> 'warnings', '[]'::jsonb)) as warnings
           from document where customer_order_id = %s order by uploaded_at, id""",
        (order_id,),
    ).fetchall()
    shipments = conn.execute(
        """select s.id, s.direction, s.tracking_number, s.delivery_note_no, s.shipped_at, s.received_at,
                  s.marked_partial, c.name as carrier
           from shipment s left join party c on c.id = s.carrier_id where s.customer_order_id = %s order by s.id""",
        (order_id,),
    ).fetchall()
    return jsonify(
        order={
            **o,
            **{
                k: full[k]
                for k in (
                    "sent_at",
                    "confirmed_at",
                    "last_received_at",
                    "last_delivered_at",
                    "ready_to_invoice_at",
                    "po_date",
                )
            },
            **co,
        },
        chain=_chain({**o, **full}),
        grid=_grid(conn, order_id, problems),
        problems=problems,
        documents=documents,
        shipments=shipments,
        events=_events(conn, order_id),
    )


@bp.get("/api/parties")
def parties():
    kind = request.args.get("kind")
    if kind not in ("customer", "distributor", "carrier"):
        raise ApiError(400, "bad_kind", "kind must be customer, distributor or carrier")
    rows = (
        db()
        .execute("select id, name, short_code, trn, sector from party where kind = %s order by name", (kind,))
        .fetchall()
    )
    return jsonify(parties=rows)


# ---------------------------------------------------------------- actions along the chain


def _check_and_respond(order_id: int, role: str):
    conn = db()
    with write_tx(conn, role):
        result = run_checks(conn, order_id, role)
    return jsonify(ok=True, order_id=order_id, check=result)


@bp.post("/api/orders/<int:order_id>/check")
def check_again(order_id: int):
    role = acting_role()
    limit_writes()
    _order_or_404(order_id)
    return _check_and_respond(order_id, role)


@bp.post("/api/orders/<int:order_id>/place-po")
def place_po(order_id: int):
    """Ops places our PO with a distributor: the customer's lines at our expected cost (85% of their price,
    to be corrected by the distributor's confirmation)."""
    role = acting_role()
    limit_writes()
    o = _order_or_404(order_id)
    if o["our_po_number"]:
        raise ApiError(409, "po_exists", f"Our PO {o['our_po_number']} already went out for this order.")
    body = request.get_json(silent=True) or {}
    distributor_id = body.get("distributor_id")
    conn = db()
    if not conn.execute(
        "select 1 from party where id = %s and kind = 'distributor'", (distributor_id,)
    ).fetchone():
        raise ApiError(400, "distributor_required", "Choose the distributor the PO goes to.")
    with write_tx(conn, role):
        year = datetime.now(UTC).year
        last = conn.execute(
            "select max(our_po_number) as n from purchase_order where our_po_number like %s",
            (f"PO-{year}-%",),
        ).fetchone()["n"]
        number = f"PO-{year}-{(int(last[-4:]) + 1) if last else 1:04d}"
        po_id = conn.execute(
            "insert into purchase_order (our_po_number, customer_order_id, distributor_id) "
            "values (%s, %s, %s) returning id",
            (number, order_id, distributor_id),
        ).fetchone()["id"]
        for ln in conn.execute(
            "select * from customer_order_line where order_id = %s order by line_no", (order_id,)
        ):
            conn.execute(
                "insert into purchase_order_line (po_id, line_no, part_number, description, qty, unit_cost) "
                "values (%s, %s, %s, %s, %s, %s)",
                (
                    po_id,
                    ln["line_no"],
                    ln["part_number"],
                    ln["description"],
                    ln["qty"],
                    (ln["unit_price"] * Decimal("0.85")).quantize(Decimal("0.01")),
                ),
            )
        result = run_checks(conn, order_id, role)
    return jsonify(ok=True, order_id=order_id, our_po_number=number, check=result), 201


@bp.post("/api/orders/<int:order_id>/deliver")
def deliver(order_id: int):
    """Ops delivers to the customer what was received, with the serial numbers that came in."""
    role = acting_role()
    limit_writes()
    conn = db()
    with write_tx(conn, role):
        conn.execute("select id from customer_order where id = %s for update", (order_id,)).fetchone()
        o = _order_or_404(order_id)
        if o["stage"] != "received":
            raise ApiError(
                409, "not_ready", "Only an order whose goods are all in can go out to the customer."
            )
        number = conn.execute(
            "select 'DO-' || to_char(now(), 'YYMMDD') || '-' || lpad((count(*) + 1)::text, 3, '0') "
            "as n from shipment where direction = 'outbound'"
        ).fetchone()["n"]
        ship_id = conn.execute(
            "insert into shipment (direction, customer_order_id, delivery_note_no, shipped_at, received_at) "
            "values ('outbound', %s, %s, now(), now()) returning id",
            (order_id, number),
        ).fetchone()["id"]
        for ln in conn.execute(
            """select sl.part_number, sl.qty,
                      array(select se.serial_no from serial se where se.shipment_line_id = sl.id
                            and se.direction = 'inbound' order by se.id) as serials
               from shipment s join shipment_line sl on sl.shipment_id = s.id
               where s.customer_order_id = %s and s.direction = 'inbound' and s.received_at is not null
               order by s.id, sl.id""",
            (order_id,),
        ):
            serials = list(ln["serials"])
            line_id = conn.execute(
                "insert into shipment_line (shipment_id, part_number, qty, serials_as_documented) "
                "values (%s, %s, %s, %s) returning id",
                (ship_id, ln["part_number"], ln["qty"], serials),
            ).fetchone()["id"]
            for s in serials:
                conn.execute(
                    "insert into serial (shipment_line_id, serial_no, direction) values (%s, %s, 'outbound')",
                    (line_id, s),
                )
        result = run_checks(conn, order_id, role)
    return jsonify(ok=True, order_id=order_id, delivery_note=number, check=result), 201


@bp.post("/api/orders/<int:order_id>/hand-to-finance")
def hand_to_finance(order_id: int):
    role = acting_role()
    limit_writes()
    o = _order_or_404(order_id)
    if o["stage"] != "delivered":
        raise ApiError(409, "not_delivered", "An order goes to finance once the customer has signed for it.")
    blocking = (
        db()
        .execute(
            "select count(*) as n from discrepancy where customer_order_id = %s and status = 'open' "
            "and severity = 'block'",
            (order_id,),
        )
        .fetchone()["n"]
    )
    if blocking:
        raise ApiError(
            409,
            "open_problems",
            f"Settle the {blocking} blocking problem(s) first; finance invoices what was agreed.",
        )
    conn = db()
    with write_tx(conn, role):
        conn.execute("update customer_order set ready_to_invoice_at = now() where id = %s", (order_id,))
    return jsonify(ok=True, order_id=order_id)
