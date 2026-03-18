"""Shared pieces of the API: JSON for decimals and dates, who is acting, and limits on writes."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from flask import current_app, g, request
from flask.json.provider import DefaultJSONProvider

from backend.config import DAILY_UPLOAD_CAP_BYTES, ROLES
from backend.db.conn import connect
from backend.errors import ApiError

WRITE_LIMIT_PER_MINUTE = 40


class JsonProvider(DefaultJSONProvider):
    """Money stays exact (a string, never a float) and dates are ISO 8601."""

    @staticmethod
    def default(o):
        if isinstance(o, Decimal):
            return f"{o:.2f}" if o == o.quantize(Decimal("0.01")) else str(o)
        if isinstance(o, datetime):
            return o.isoformat()
        if isinstance(o, date):
            return o.isoformat()
        if isinstance(o, (set, frozenset, tuple)):
            return list(o)
        return DefaultJSONProvider.default(o)


def db():
    """One connection per request, closed when the request ends (see app.teardown_appcontext)."""
    if "db" not in g:
        g.db = connect(current_app.config.get("DB_KIND", "pooled"), autocommit=True)
    return g.db


def close_db(_exc=None) -> None:
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def acting_role() -> str:
    role = request.headers.get("X-Role", "").strip().lower()
    if role not in ROLES:
        raise ApiError(400, "role_required", "Say who is acting: send X-Role as sales, ops or finance.")
    return role


def client_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return (forwarded.split(",")[0].strip() or request.remote_addr or "unknown")[:64]


def limit_writes(cost: int = 1) -> None:
    """Count writes per visitor per minute in the database; refuse over the limit."""
    window = datetime.now(UTC).replace(second=0, microsecond=0)
    conn = db()
    with conn.transaction():
        hits = conn.execute(
            """insert into rate_limit (client_key, window_start, hits) values (%s, %s, %s)
               on conflict (client_key, window_start) do update set hits = rate_limit.hits + excluded.hits
               returning hits""",
            (client_key(), window, cost),
        ).fetchone()["hits"]
        conn.execute("delete from rate_limit where window_start < %s", (window - timedelta(minutes=10),))
    if hits > WRITE_LIMIT_PER_MINUTE:
        raise ApiError(
            429, "slow_down", "Too many changes in a minute from here. Wait a moment and try again."
        )


def check_daily_upload_cap(size: int) -> None:
    used = (
        db()
        .execute(
            """select coalesce((select sum(size_bytes) from pending_upload where created_at > now() - interval '1 day'), 0)
                + coalesce((select sum(size_bytes) from document where uploaded_by_role <> 'system'
                            and uploaded_at > now() - interval '1 day'), 0) as used"""
        )
        .fetchone()["used"]
    )
    if used + size > DAILY_UPLOAD_CAP_BYTES:
        raise ApiError(
            507, "daily_upload_cap", "The demo has taken its daily share of uploads. It resets overnight."
        )
