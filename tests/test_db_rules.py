"""The database refuses bad data by itself, whatever code writes to it."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

from backend.db.conn import write_tx
from backend.db.migrate import MigrationError, migrate

pytestmark = pytest.mark.db


def _party(db, kind, name, code, trn=None):
    return db.execute(
        "insert into party (kind, name, short_code, trn) values (%s, %s, %s, %s) returning id",
        (kind, name, code, trn),
    ).fetchone()["id"]


def _order(db, customer_id, po="PO-77"):
    return db.execute(
        "insert into customer_order (po_number, customer_id, po_date) values (%s, %s, current_date) returning id",
        (po, customer_id),
    ).fetchone()["id"]


def _chain(db):
    cust = _party(db, "customer", "Test Customer", "TC", "100123456789012")
    dist = _party(db, "distributor", "Test Distributor", "TD", "100987654321098")
    carrier = _party(db, "carrier", "Test Carrier", "TCR")
    order = _order(db, cust)
    po = db.execute(
        "insert into purchase_order (our_po_number, customer_order_id, distributor_id) "
        "values ('PO-2026-0001', %s, %s) returning id",
        (order, dist),
    ).fetchone()["id"]
    return cust, dist, carrier, order, po


def _shipment_line(db, order, po, carrier, direction):
    ship = db.execute(
        "insert into shipment (direction, customer_order_id, po_id, carrier_id) values (%s, %s, %s, %s) returning id",
        (direction, order, po, carrier),
    ).fetchone()["id"]
    return db.execute(
        "insert into shipment_line (shipment_id, part_number, qty) values (%s, 'R760-BASE', 2) returning id",
        (ship,),
    ).fetchone()["id"]


def test_bad_trn_is_refused(db):
    with pytest.raises(psycopg.errors.CheckViolation):
        _party(db, "customer", "Bad TRN Co", "BT", "12345")


def test_negative_quantity_is_refused(db):
    cust = _party(db, "customer", "Test Customer", "TC")
    order = _order(db, cust)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into customer_order_line (order_id, line_no, part_number, description, qty, unit_price) "
            "values (%s, 1, 'R760-BASE', 'Server', -1, 10)",
            (order,),
        )


def test_same_serial_cannot_arrive_twice(db):
    _, _, carrier, order, po = _chain(db)
    line = _shipment_line(db, order, po, carrier, "inbound")
    db.execute(
        "insert into serial (shipment_line_id, serial_no, direction) values (%s, 'SN12345', 'inbound')",
        (line,),
    )
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(
            "insert into serial (shipment_line_id, serial_no, direction) values (%s, 'SN12345', 'inbound')",
            (line,),
        )


def test_serial_direction_must_match_its_shipment(db):
    _, _, carrier, order, po = _chain(db)
    line = _shipment_line(db, order, po, carrier, "inbound")
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into serial (shipment_line_id, serial_no, direction) values (%s, 'SN99999', 'outbound')",
            (line,),
        )


def test_po_must_go_to_a_distributor(db):
    cust = _party(db, "customer", "Test Customer", "TC")
    order = _order(db, cust)
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "insert into purchase_order (our_po_number, customer_order_id, distributor_id) "
            "values ('PO-2026-0002', %s, %s)",
            (order, cust),
        )


def test_duplicate_document_is_refused(db):
    sql = (
        "insert into document (kind, filename, mime, sha256, size_bytes, content, extracted, extractor_version, "
        "uploaded_by_role) values ('customer_po', 'a.pdf', 'application/pdf', %s, 4, '\\x25504446', '{}', 'x', 'ops')"
    )
    digest = "a" * 64
    db.execute(sql, (digest,))
    with pytest.raises(psycopg.errors.UniqueViolation):
        db.execute(sql, (digest,))


def test_resolving_a_discrepancy_needs_a_note(db):
    _, _, _, order, _ = _chain(db)
    run = db.execute(
        "insert into check_run (customer_order_id, engine_version) values (%s, 't') returning id", (order,)
    ).fetchone()["id"]
    disc = db.execute(
        "insert into discrepancy (check_run_id, customer_order_id, code, severity, stage, explanation, fingerprint) "
        "values (%s, %s, 'QTY_SHORT', 'block', 'confirmed', 'x', 'f1') returning id",
        (run, order),
    ).fetchone()["id"]
    with pytest.raises(psycopg.errors.CheckViolation):
        db.execute(
            "update discrepancy set status = 'accepted', resolved_at = now(), resolved_by_role = 'ops' where id = %s",
            (disc,),
        )


def test_audit_log_records_role_and_backdated_time(db):
    cust = _party(db, "customer", "Test Customer", "TC")
    db.commit()
    when = datetime(2026, 10, 1, 9, 30, tzinfo=UTC)
    with write_tx(db, "sales", at=when):
        order = _order(db, cust, po="PO-AUDIT")
    row = db.execute(
        "select actor_role, at, action, customer_order_id from event where table_name = 'customer_order'"
    ).fetchone()
    assert row["actor_role"] == "sales"
    assert row["at"] == when
    assert row["action"] == "insert"
    assert row["customer_order_id"] == order


def test_audit_role_does_not_leak_past_the_transaction(db):
    cust = _party(db, "customer", "Test Customer", "TC")
    db.commit()
    with write_tx(db, "finance"):
        _order(db, cust, po="PO-1")
    with db.transaction():
        _order(db, cust, po="PO-2")
    roles = [r["actor_role"] for r in db.execute("select actor_role from event order by id")]
    assert roles == ["finance", "system"]


def test_board_view_puts_a_new_order_with_sales(db):
    cust = _party(db, "customer", "Test Customer", "TC")
    with write_tx(db, "sales", at=datetime.now(UTC) - timedelta(days=3)):
        order = _order(db, cust)
    row = db.execute(
        "select stage, whose_turn, days_in_stage from order_chain where id = %s", (order,)
    ).fetchone()
    assert (row["stage"], row["whose_turn"]) == ("po_received", "sales")
    assert row["days_in_stage"] == 0  # received_at defaults to now(); stage age comes from received_at


def test_migrate_is_idempotent_and_refuses_edited_files(db, tmp_path, monkeypatch):
    assert migrate(db) == []
    db.execute("update schema_migrations set checksum = 'tampered' where name = '001_core.sql'")
    db.commit()
    try:
        with pytest.raises(MigrationError):
            migrate(db)
    finally:
        from backend.db.migrate import MIGRATIONS, checksum

        db.rollback()
        db.execute(
            "update schema_migrations set checksum = %s where name = '001_core.sql'",
            (checksum(MIGRATIONS / "001_core.sql"),),
        )
        db.commit()
