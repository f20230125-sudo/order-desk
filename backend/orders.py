"""Orders as stored: turn database rows into the check engine's dataclasses, and store what it finds.

Running the checks again keeps each problem's identity (its fingerprint), so an issue someone accepted
stays accepted with its note, a new one opens, and an open one the check no longer finds is closed with
a note saying so.
"""

from datetime import datetime

import psycopg

from backend.check.engine import ENGINE_VERSION, check
from backend.check.model import Confirmation, CustomerPO, Line, OrderBundle, OurPO, Shipment, ShipmentLine


def load_bundle(conn: psycopg.Connection, order_id: int) -> OrderBundle:
    co = conn.execute("select * from customer_order where id = %s", (order_id,)).fetchone()
    if co is None:
        raise LookupError(order_id)
    cust_lines = [
        Line(r["line_no"], r["part_number"], r["description"], r["qty"], r["unit_price"])
        for r in conn.execute(
            "select * from customer_order_line where order_id = %s order by line_no", (order_id,)
        )
    ]
    customer_po = CustomerPO(
        co["po_number"],
        co["po_date"],
        cust_lines,
        required_by=co["required_by"],
        currency=co["currency"],
        vat_rate=co["vat_rate"],
        subtotal=co["subtotal"],
        vat_amount=co["vat_amount"],
        total=co["total"],
    )
    po = conn.execute("select * from purchase_order where customer_order_id = %s", (order_id,)).fetchone()
    our_po, confirmations = None, []
    if po:
        our_po = OurPO(
            po["our_po_number"],
            [
                Line(r["line_no"], r["part_number"], r["description"], r["qty"], r["unit_cost"])
                for r in conn.execute(
                    "select * from purchase_order_line where po_id = %s order by line_no", (po["id"],)
                )
            ],
        )
        for vc in conn.execute(
            "select * from vendor_confirmation where po_id = %s order by confirmed_at, id", (po["id"],)
        ).fetchall():
            lines = [
                Line(
                    r["line_no"],
                    r["part_number"],
                    r["description"],
                    r["qty"],
                    r["unit_cost"],
                    substitutes_part=r["substitutes_part"],
                )
                for r in conn.execute(
                    "select * from vendor_confirmation_line where confirmation_id = %s order by line_no",
                    (vc["id"],),
                )
            ]
            confirmations.append(Confirmation(vc["confirmation_no"], vc["referenced_po"], lines, vc["eta"]))
    shipments = []
    for s in conn.execute(
        "select * from shipment where customer_order_id = %s order by id", (order_id,)
    ).fetchall():
        lines = [
            ShipmentLine(r["part_number"], r["qty"], list(r["serials_as_documented"]))
            for r in conn.execute(
                "select * from shipment_line where shipment_id = %s order by id", (s["id"],)
            )
        ]
        shipments.append(
            Shipment(
                s["direction"],
                s["delivery_note_no"] or s["tracking_number"] or f"shipment {s['id']}",
                lines,
                received=s["received_at"] is not None,
                marked_partial=s["marked_partial"],
            )
        )
    serialised = frozenset(
        r["part_number"] for r in conn.execute("select part_number from product where serialised")
    )
    # Serials this order's paperwork lists that are booked in on another order's delivery.
    elsewhere = {
        r["serial_no"]: r["ref"]
        for r in conn.execute(
            """select se.serial_no, coalesce(s.delivery_note_no, s.tracking_number, 'another delivery') as ref
           from serial se join shipment_line sl on sl.id = se.shipment_line_id join shipment s on s.id = sl.shipment_id
           where se.direction = 'inbound' and s.customer_order_id <> %s
             and se.serial_no in (select unnest(sl2.serials_as_documented) from shipment_line sl2
                                  join shipment s2 on s2.id = sl2.shipment_id where s2.customer_order_id = %s)""",
            (order_id, order_id),
        )
    }
    return OrderBundle(customer_po, our_po, confirmations, shipments, serialised, elsewhere)


def run_checks(conn: psycopg.Connection, order_id: int, role: str, at: datetime | None = None) -> dict:
    """Check the order and reconcile the stored problems. Call inside a write transaction."""
    findings = check(load_bundle(conn, order_id))
    run = conn.execute(
        "insert into check_run (customer_order_id, engine_version, ran_at) "
        "values (%s, %s, coalesce(%s, now())) returning id",
        (order_id, ENGINE_VERSION, at),
    ).fetchone()
    existing = {
        r["fingerprint"]: r
        for r in conn.execute(
            "select id, fingerprint, status from discrepancy where customer_order_id = %s", (order_id,)
        )
    }
    opened = 0
    for f in findings:
        if f.fingerprint in existing:
            # Same problem again: keep its status and note, refresh the wording and values.
            conn.execute(
                "update discrepancy set explanation = %s, expected = %s, found = %s, check_run_id = %s "
                "where id = %s",
                (f.explanation, f.expected, f.found, run["id"], existing[f.fingerprint]["id"]),
            )
            continue
        conn.execute(
            """insert into discrepancy (check_run_id, customer_order_id, code, severity, stage, part_number,
                   expected, found, explanation, fingerprint)
               values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (
                run["id"],
                order_id,
                f.code,
                f.severity,
                f.stage,
                f.part_number,
                f.expected,
                f.found,
                f.explanation,
                f.fingerprint,
            ),
        )
        opened += 1
    still = {f.fingerprint for f in findings}
    closed = 0
    for fp, row in existing.items():
        if fp not in still and row["status"] == "open":
            conn.execute(
                "update discrepancy set status = 'fixed', resolved_at = coalesce(%s, now()), "
                "resolved_by_role = %s, resolution_note = 'No longer found when the order was checked again.' "
                "where id = %s",
                (at, role if role != "system" else "ops", row["id"]),
            )
            closed += 1
    return {"check_run_id": run["id"], "findings": len(findings), "opened": opened, "closed": closed}
