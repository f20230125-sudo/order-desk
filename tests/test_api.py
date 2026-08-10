"""The API end to end against a seeded test database: what the screens and a curl user can do."""

import io
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from app import create_app
from backend.check.model import Confirmation
from backend.db.conn import write_tx
from backend.models import GoodsInIn
from backend.orders import run_checks
from synth.generate import documents_for
from synth.render_pdf import confirmation_a
from synth.scenario import build

pytestmark = pytest.mark.db

OPS = {"X-Role": "ops"}
SALES = {"X-Role": "sales"}
FINANCE = {"X-Role": "finance"}


@pytest.fixture(scope="module")
def client(migrated_db):
    from backend.db.conn import connect
    from backend.db.seed import seed

    with connect("test") as conn, conn.transaction():
        seed(conn, reset=True)
    app = create_app(db_kind="test")
    app.config["TESTING"] = True
    return app.test_client()


def _upload(client, data: bytes, name: str, headers=OPS, kind=None):
    form = {"file": (io.BytesIO(data), name)}
    if kind:
        form["kind"] = kind
    return client.post("/api/intake", data=form, headers=headers, content_type="multipart/form-data")


def _values(extracted: dict) -> dict:
    return {k: v["value"] for k, v in extracted["fields"].items()}


def test_board_lists_every_order_with_a_summary(client):
    r = client.get("/api/board").get_json()
    assert len(r["orders"]) == 42
    assert r["summary"]["total"] == 42
    assert r["summary"]["open"] == 42 - 7  # seven are with finance already
    first = r["orders"][0]
    assert {"po_number", "stage", "whose_turn", "days_in_stage", "problems", "first_problem"} <= set(first)


def test_board_filters(client):
    ops = client.get("/api/board?turn=ops").get_json()["orders"]
    assert ops and all(o["whose_turn"] == "ops" for o in ops)
    with_problems = client.get("/api/board?problems=1").get_json()["orders"]
    assert with_problems and all(o["problems"] > 0 for o in with_problems)
    assert client.get("/api/board?stage=nonsense").status_code == 400


def test_search_finds_an_order_by_serial_tracking_or_po(client):
    order = next(o for o in build() if o.inbound and o.inbound[0].lines[0].serials)
    serial = order.inbound[0].lines[0].serials[0]
    by_serial = client.get(f"/api/board?q={serial}").get_json()["orders"]
    assert [o["po_number"] for o in by_serial] == [order.customer_po.po_number]
    tracking = order.tracking[order.inbound[0].reference]
    assert client.get(f"/api/board?q={tracking[:6]}").get_json()["orders"]
    assert (
        client.get(f"/api/board?q={order.our_po.our_po_number}").get_json()["orders"][0]["po_number"]
        == order.customer_po.po_number
    )


def test_order_detail_has_chain_grid_problems_documents_and_history(client):
    board = client.get("/api/board?problems=1").get_json()["orders"]
    d = client.get(f"/api/orders/{board[0]['id']}").get_json()
    assert [s["key"] for s in d["chain"]][0] == "po_received" and len(d["chain"]) == 6
    assert d["grid"] and d["problems"] and d["documents"] and d["events"]
    assert d["events"][0]["text"].startswith("Customer PO")
    assert client.get("/api/orders/999999").status_code == 404


def test_writes_need_a_role(client):
    r = client.post("/api/orders/1/check")
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "role_required"


def test_same_file_twice_is_refused(client):
    # The exact bytes of a document already on an order (the seed dates its documents by today's date, so
    # regenerating one here would make a different file).
    doc = client.get("/api/orders/1").get_json()["documents"][0]
    data = client.get(f"/api/documents/{doc['id']}/file").data
    r = _upload(client, data, "again.pdf")
    assert r.status_code == 409
    assert r.get_json()["error"]["code"] == "already_received"
    assert r.get_json()["error"]["details"]["order_id"] == 1


def test_only_pdf_and_email_files(client):
    r = _upload(client, b"PK\x03\x04 a zip", "x.zip")
    assert r.status_code == 415


def test_new_customer_po_round_trip(client):
    other = build(seed=99)[0]  # a different order: same customers, new PO number
    name, data, _t = documents_for(other)[0]
    up = _upload(client, data, name, headers=SALES)
    assert up.status_code == 201, up.get_json()
    body = up.get_json()
    assert body["kind"] == "customer_po"
    assert body["suggestion"]["customer"]["name"] == other.customer.name  # matched by the buyer's TRN
    v = _values(body["extracted"])
    payload = {
        "customer_id": body["suggestion"]["customer"]["id"],
        "po_number": v["po_number"],
        "po_date": v["po_date"],
        "required_by": v.get("required_by"),
        "subtotal": v.get("subtotal"),
        "vat_amount": v.get("vat_amount"),
        "total": v.get("total"),
        "lines": [
            {
                "part_number": ln["part_number"]["value"],
                "description": ln.get("description", {}).get("value", ""),
                "qty": ln["qty"]["value"],
                "unit_price": ln["unit_price"]["value"],
            }
            for ln in body["extracted"]["lines"]
        ],
    }
    done = client.post(f"/api/intake/{body['pending_id']}/confirm", json=payload, headers=SALES)
    assert done.status_code == 201, done.get_json()
    order_id = done.get_json()["order_id"]
    d = client.get(f"/api/orders/{order_id}").get_json()
    assert d["order"]["stage"] == "po_received" and d["order"]["whose_turn"] == "sales"
    assert d["documents"][0]["kind"] == "customer_po"
    # the same PO number from the same customer cannot be booked twice
    again = client.post(
        "/api/intake",
        data={"file": (io.BytesIO(data + b"\n%comment"), "copy.pdf")},
        headers=SALES,
        content_type="multipart/form-data",
    ).get_json()
    dup = client.post(f"/api/intake/{again['pending_id']}/confirm", json=payload, headers=SALES)
    assert dup.status_code == 409 and dup.get_json()["error"]["code"] == "po_exists"


def test_confirmation_with_a_shortfall_raises_a_problem(client):
    orders = build()
    o = next(x for x in orders if x.stage == "po_sent" and not x.planted and x.our_po.lines[0].qty > 1)
    first = o.our_po.lines[0]
    short = [replace(first, qty=first.qty - 1)] + o.our_po.lines[1:]
    o.confirmation = Confirmation(
        "FVD-SOC-777001", o.our_po.our_po_number, short, eta=o.customer_po.required_by
    )
    data = confirmation_a(o)
    up = _upload(client, data, "conf.pdf").get_json()
    assert up["kind"] == "vendor_confirmation"
    order = up["suggestion"]["order"]
    assert order["our_po_number"] == o.our_po.our_po_number  # found by the PO number it quotes
    v = _values(up["extracted"])
    payload = {
        "order_id": order["id"],
        "confirmation_no": v["confirmation_no"],
        "referenced_po": v["referenced_po"],
        "eta": v.get("eta"),
        "lines": [
            {
                "part_number": ln["part_number"]["value"],
                "qty": ln["qty"]["value"],
                "unit_price": ln["unit_price"]["value"],
            }
            for ln in up["extracted"]["lines"]
        ],
    }
    done = client.post(f"/api/intake/{up['pending_id']}/confirm", json=payload, headers=OPS)
    assert done.status_code == 201, done.get_json()
    d = client.get(f"/api/orders/{order['id']}").get_json()
    codes = [(p["code"], p["part_number"]) for p in d["problems"] if p["status"] == "open"]
    assert ("QTY_SHORT", first.part_number) in codes
    assert d["order"]["stage"] == "confirmed" and d["order"]["whose_turn"] == "ops"


def test_bad_values_are_explained_field_by_field(client):
    other = build(seed=98)[1]
    name, data, _t = documents_for(other)[0]
    up = _upload(client, data, name, headers=SALES).get_json()
    r = client.post(
        f"/api/intake/{up['pending_id']}/confirm",
        headers=SALES,
        json={
            "customer_id": 1,
            "po_number": "X1",
            "po_date": "2026-13-40",
            "lines": [{"part_number": "x", "qty": 0, "unit_price": "-1"}],
        },
    )
    assert r.status_code == 400
    fields = {p["field"] for p in r.get_json()["error"]["details"]}
    assert {"po_number", "po_date", "lines.0.part_number", "lines.0.qty", "lines.0.unit_price"} <= fields


def test_settling_a_problem_needs_a_note_and_updates_the_board(client):
    board = client.get("/api/board?problems=1").get_json()["orders"]
    target = board[0]
    problem = next(
        p
        for p in client.get(f"/api/orders/{target['id']}").get_json()["problems"]
        if p["status"] == "open" and p["severity"] in ("block", "warn")
    )
    r = client.patch(
        f"/api/discrepancies/{problem['id']}", json={"status": "accepted", "note": ""}, headers=SALES
    )
    assert r.status_code == 400 and r.get_json()["error"]["code"] == "note_required"
    r = client.patch(
        f"/api/discrepancies/{problem['id']}",
        json={"status": "accepted", "note": "Agreed by phone."},
        headers=SALES,
    )
    assert r.status_code == 200 and r.get_json()["problem"]["resolved_by_role"] == "sales"
    after = next(o for o in client.get("/api/board").get_json()["orders"] if o["id"] == target["id"])
    assert after["problems"] == target["problems"] - 1
    events = client.get(f"/api/orders/{target['id']}").get_json()["events"]
    assert events[-1]["text"].startswith("Marked accepted") and events[-1]["role"] == "sales"


def test_moving_an_order_along_the_chain(client):
    board = client.get("/api/board").get_json()["orders"]
    new = next(o for o in board if o["stage"] == "po_received" and o["problems"] == 0)
    dist = client.get("/api/parties?kind=distributor").get_json()["parties"][0]
    r = client.post(f"/api/orders/{new['id']}/place-po", json={"distributor_id": dist["id"]}, headers=OPS)
    assert r.status_code == 201 and r.get_json()["our_po_number"].startswith("PO-")
    assert (
        client.post(
            f"/api/orders/{new['id']}/place-po", json={"distributor_id": dist["id"]}, headers=OPS
        ).status_code
        == 409
    )
    received = next(o for o in board if o["stage"] == "received" and o["problems"] == 0)
    assert client.post(f"/api/orders/{received['id']}/deliver", headers=OPS).status_code == 201
    assert client.post(f"/api/orders/{received['id']}/hand-to-finance", headers=FINANCE).status_code == 200
    final = client.get(f"/api/orders/{received['id']}").get_json()["order"]
    assert final["stage"] == "ready_to_invoice" and final["whose_turn"] is None


def test_documents_are_served_safely(client):
    d = client.get("/api/orders/1").get_json()["documents"][0]
    r = client.get(f"/api/documents/{d['id']}/file")
    assert r.status_code == 200 and r.data[:5] == b"%PDF-"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in r.headers["Content-Security-Policy"]


def test_deep_links_get_the_app_and_unknown_api_paths_get_json(client):
    assert client.get("/api/nope").get_json()["error"]["code"] == "not_found"
    r = client.get("/orders/42")
    assert r.status_code in (200, 503)  # 503 only when the web app has not been built
    if r.status_code == 200:
        # built files are served as themselves, and nothing outside public/ is reachable
        assert client.get("/favicon.svg").mimetype == "image/svg+xml"
        assert client.get("/index.html").mimetype == "text/html"
        assert client.get("/../app.py").status_code in (200, 404)  # normalised to /app.py: the shell
        assert b"create_app" not in client.get("/%2e%2e/app.py").data


def test_writes_are_rate_limited(client, monkeypatch):
    from backend.api import common

    monkeypatch.setattr(common, "WRITE_LIMIT_PER_MINUTE", 3)
    codes = [
        client.post("/api/orders/1/check", headers=OPS, environ_base={"REMOTE_ADDR": "10.9.9.9"}).status_code
        for _ in range(5)
    ]
    assert codes[:3] == [200, 200, 200] and 429 in codes[3:]


@pytest.fixture
def goods_order(db):
    from test_db_rules import _chain

    from backend.api.intake import _save_confirmation, _save_goods_in
    from backend.models import ConfirmationIn

    _, _, _, order, po = _chain(db)
    db.execute(
        "insert into customer_order_line (order_id, line_no, part_number, description, qty, unit_price) "
        "values (%s, 1, 'PER760-XS2', 'Server', 2, 100)",
        (order,),
    )
    db.execute(
        "insert into purchase_order_line (po_id, line_no, part_number, description, qty, unit_cost) "
        "values (%s, 1, 'PER760-XS2', 'Server', 2, 100)",
        (po,),
    )
    _save_confirmation(
        db,
        ConfirmationIn(
            kind="vendor_confirmation",
            order_id=order,
            confirmation_no="CONF-1",
            referenced_po="PO-2026-0001",
            lines=[
                {
                    "part_number": "PER770-XS2",
                    "description": "Server",
                    "qty": 2,
                    "unit_price": "100",
                    "substitutes_part": "PER760-XS2",
                }
            ],
        ),
    )
    goods = GoodsInIn(
        kind="shipment_email",
        order_id=order,
        delivery_note_no="DN-TEST",
        lines=[{"part_number": "PER770-XS2", "qty": 2, "serials": ["SERIAL1", "SERIAL2"]}],
    )
    _save_goods_in(db, goods)
    run_checks(db, order, "ops")
    db.execute(
        "update discrepancy set status = 'accepted', resolved_at = now(), resolved_by_role = 'sales', "
        "resolution_note = 'Customer approved.' where customer_order_id = %s and code = 'SUBSTITUTION'",
        (order,),
    )
    db.commit()
    return order, goods


def test_deliver_records_received_substitute_and_serials(db, goods_order):
    order, _ = goods_order
    app = create_app(db_kind="test")
    r = app.test_client().post(f"/api/orders/{order}/deliver", headers=OPS)
    assert r.status_code == 201, r.get_json()
    lines = db.execute(
        "select sl.part_number, sl.qty, sl.serials_as_documented from shipment_line sl "
        "join shipment s on s.id = sl.shipment_id where s.customer_order_id = %s and s.direction = 'outbound'",
        (order,),
    ).fetchall()
    assert lines == [{"part_number": "PER770-XS2", "qty": 2, "serials_as_documented": ["SERIAL1", "SERIAL2"]}]
    assert db.execute("select stage from board where id = %s", (order,)).fetchone()["stage"] == "delivered"
    assert (
        db.execute(
            "select code from discrepancy where customer_order_id = %s and status = 'open'", (order,)
        ).fetchall()
        == []
    )


@pytest.mark.parametrize("change", ["quantity", "extra", "missing"])
def test_second_goods_document_rejects_changed_lines(db, goods_order, change):
    from backend.api.intake import _save_goods_in
    from backend.errors import ApiError

    order, goods = goods_order
    data = goods.model_dump()
    data["kind"] = "delivery_note"
    if change == "quantity":
        data["lines"][0]["qty"] = 3
    elif change == "extra":
        data["lines"].append({"part_number": "SFP28-SR-25G", "qty": 1})
    else:
        data["lines"] = [{"part_number": "SFP28-SR-25G", "qty": 1}]
    with pytest.raises(ApiError) as exc, write_tx(db, "ops"):
        _save_goods_in(db, GoodsInIn(**data))
    assert exc.value.code == "delivery_conflict"
    assert (
        db.execute(
            "select sum(sl.qty) as qty from shipment_line sl join shipment s on s.id = sl.shipment_id "
            "where s.customer_order_id = %s",
            (order,),
        ).fetchone()["qty"]
        == 2
    )


def test_concurrent_deliveries_create_one_dispatch(db, goods_order):
    order, _ = goods_order
    app = create_app(db_kind="test")

    def deliver():
        with app.test_client() as c:
            return c.post(f"/api/orders/{order}/deliver", headers=OPS).status_code

    db.execute("select id from customer_order where id = %s for update", (order,))
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(deliver) for _ in range(2)]
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                db.execute("select pg_stat_clear_snapshot()")
                waiting = db.execute(
                    "select count(*) as n from pg_stat_activity where application_name = 'order-desk' "
                    "and pid <> pg_backend_pid() and wait_event_type = 'Lock'"
                ).fetchone()["n"]
                if waiting >= 2:
                    break
                time.sleep(0.01)
            assert waiting >= 2
        finally:
            db.rollback()
        assert sorted(f.result(timeout=10) for f in futures) == [201, 409]
    assert (
        db.execute(
            "select count(*) as n from shipment where customer_order_id = %s and direction = 'outbound'",
            (order,),
        ).fetchone()["n"]
        == 1
    )


def test_expired_uploads_still_count_toward_daily_cap(db, monkeypatch):
    from backend.api import common
    from backend.errors import ApiError

    app = create_app(db_kind="test")
    monkeypatch.setattr(common, "db", lambda: db)
    monkeypatch.setattr(common, "DAILY_UPLOAD_CAP_BYTES", 50)
    with app.app_context(), db.transaction():
        common.check_daily_upload_cap(40)
        db.execute(
            "insert into pending_upload (kind, filename, mime, sha256, size_bytes, content, extracted, expires_at) "
            "values ('customer_po', 'a.pdf', 'application/pdf', %s, 40, %s, '{}', now() - interval '1 second')",
            ("a" * 64, b"test"),
        )
        db.execute("delete from pending_upload where expires_at < now()")
        common.check_daily_upload_cap(1)
        with pytest.raises(ApiError) as exc:
            common.check_daily_upload_cap(10)
        assert exc.value.code == "daily_upload_cap"
