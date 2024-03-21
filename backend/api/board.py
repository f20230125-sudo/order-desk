"""The order board: every order, where it stands, whose turn it is, and its first problem."""

from flask import Blueprint, jsonify, request

from backend.api.common import db
from backend.errors import ApiError

bp = Blueprint("board", __name__)

STAGES = ("po_received", "po_sent", "confirmed", "received", "delivered", "ready_to_invoice")
BOARD_COLUMNS = """id, po_number, customer_name, sector, our_po_number, distributor_name, stage, stage_no,
    whose_turn, days_in_stage, problems, notes, first_problem, total, currency, required_by, eta,
    eta_after_required, received_at"""


@bp.get("/api/board")
def board():
    stage = request.args.get("stage") or None
    turn = request.args.get("turn") or None
    problems_only = request.args.get("problems") in ("1", "true", "yes")
    q = (request.args.get("q") or "").strip()
    if stage and stage not in STAGES:
        raise ApiError(400, "bad_stage", f"Stage must be one of {', '.join(STAGES)}.")
    if turn and turn not in ("sales", "ops", "finance"):
        raise ApiError(400, "bad_turn", "Turn must be sales, ops or finance.")
    where, params = [], []
    if stage:
        where.append("stage = %s")
        params.append(stage)
    if turn:
        where.append("whose_turn = %s")
        params.append(turn)
    if problems_only:
        where.append("problems > 0")
    if q:
        # One box finds an order by its PO number, our PO number, a tracking number or a serial number.
        like = q.lower() + "%"
        where.append("""(lower(po_number) like %s or lower(our_po_number) like %s
            or exists (select 1 from shipment s where s.customer_order_id = board.id
                       and (lower(s.tracking_number) like %s or lower(s.delivery_note_no) like %s))
            or exists (select 1 from shipment s join shipment_line sl on sl.shipment_id = s.id
                       where s.customer_order_id = board.id and upper(%s) = any(sl.serials_as_documented)))""")
        params += [like, like, like, like, q]
    sql = f"select {BOARD_COLUMNS} from board"
    if where:
        sql += " where " + " and ".join(where)
    # Open work first: orders with a turn, blocking problems, then the longest wait.
    sql += " order by (whose_turn is null), problems > 0 desc, days_in_stage desc, id"
    rows = db().execute(sql, params).fetchall()
    summary = (
        db()
        .execute(
            """select count(*) filter (where stage <> 'ready_to_invoice') as open,
                  count(*) filter (where whose_turn = 'sales') as sales,
                  count(*) filter (where whose_turn = 'ops') as ops,
                  count(*) filter (where whose_turn = 'finance') as finance,
                  count(*) filter (where problems > 0) as with_problems,
                  count(*) as total
           from board"""
        )
        .fetchone()
    )
    return jsonify(
        orders=rows,
        summary=summary,
        filters={"stage": stage, "turn": turn, "problems": problems_only, "q": q or None},
    )
