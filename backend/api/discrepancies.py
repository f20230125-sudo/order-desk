"""Settling a problem: accept it as it is, or say it was fixed. Either way, a note says why."""

from flask import Blueprint, jsonify, request

from backend.api.common import acting_role, db, limit_writes
from backend.db.conn import write_tx
from backend.errors import ApiError

bp = Blueprint("discrepancies", __name__)


@bp.patch("/api/discrepancies/<int:disc_id>")
def settle(disc_id: int):
    role = acting_role()
    limit_writes()
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    note = (body.get("note") or "").strip()
    if status not in ("accepted", "fixed", "open"):
        raise ApiError(400, "bad_status", "Status must be accepted, fixed or open.")
    if status != "open" and len(note) < 3:
        raise ApiError(400, "note_required", "Write a short note saying why, so the next person knows.")
    if len(note) > 500:
        raise ApiError(400, "note_too_long", "Keep the note under 500 characters.")
    conn = db()
    with write_tx(conn, role):
        row = conn.execute(
            """update discrepancy set status = %s,
                   resolution_note = case when %s = 'open' then null else %s end,
                   resolved_by_role = case when %s = 'open' then null else %s end,
                   resolved_at = case when %s = 'open' then null else now() end
               where id = %s
               returning id, customer_order_id, code, severity, status, resolution_note, resolved_by_role, resolved_at""",
            (status, status, note, status, role, status, disc_id),
        ).fetchone()
    if row is None:
        raise ApiError(404, "no_such_problem", f"There is no problem {disc_id}.")
    return jsonify(problem=row)
