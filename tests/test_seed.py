"""The seeded demo database: every order where the story put it, with a believable history."""

import pytest

from backend.db.conn import write_tx
from backend.db.seed import seed
from backend.orders import run_checks
from synth.scenario import build

pytestmark = pytest.mark.db


@pytest.fixture(scope="module")
def seeded(migrated_db):
    from backend.db.conn import connect

    with connect("test") as conn:
        with conn.transaction():
            seed(conn, reset=True)
        yield conn


def test_every_order_is_at_the_stage_its_story_reached(seeded):
    want = {o.customer_po.po_number: o.stage for o in build()}
    got = {r["po_number"]: r["stage"] for r in seeded.execute("select po_number, stage from board")}
    assert got == want


def test_history_is_written_by_the_roles_that_did_the_work(seeded):
    roles = {
        r["table_name"]: r["roles"]
        for r in seeded.execute(
            "select table_name, array_agg(distinct actor_role order by actor_role) as roles from event group by 1"
        )
    }
    assert roles["customer_order"] == ["finance", "sales"]  # booked by sales, handed over by finance
    assert roles["purchase_order"] == ["ops"]
    assert set(roles["discrepancy"]) <= {"sales", "ops", "finance"}


def test_history_happens_in_order(seeded):
    bad = seeded.execute(
        """select co.po_number from customer_order co join purchase_order po on po.customer_order_id = co.id
           where po.sent_at < co.received_at"""
    ).fetchall()
    assert bad == []


def test_documents_were_read_by_the_extractor(seeded):
    rows = seeded.execute(
        "select kind, extracted ->> 'extractor_version' as v, count(*) as n from document group by 1, 2"
    )
    assert {r["kind"] for r in rows} == {
        "customer_po",
        "vendor_confirmation",
        "delivery_note",
        "shipment_email",
    }


def test_checking_again_keeps_decisions(seeded):
    accepted = seeded.execute(
        "select customer_order_id as id, fingerprint from discrepancy where status = 'accepted' limit 1"
    ).fetchone()
    with write_tx(seeded, "ops"):
        result = run_checks(seeded, accepted["id"], "ops")
    assert result["opened"] == 0 and result["closed"] == 0
    status = seeded.execute(
        "select status from discrepancy where customer_order_id = %s and fingerprint = %s",
        (accepted["id"], accepted["fingerprint"]),
    ).fetchone()["status"]
    assert status == "accepted"


def test_every_problem_code_is_on_the_board_somewhere(seeded):
    codes = {r["code"] for r in seeded.execute("select distinct code from discrepancy")}
    assert len(codes) == 14
