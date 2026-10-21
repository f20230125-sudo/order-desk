"""Database connections.

One short connection per request: serverless instances are frozen between requests and Neon sleeps
after five idle minutes, so a client-side pool would mostly hold dead sockets. Neon's pooler runs
PgBouncer in transaction mode, which is why prepared statements are turned off and anything
session-scoped is set with set_config(..., true) inside a transaction instead of SET.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

import psycopg
from psycopg.rows import dict_row

from backend.config import ROLES, database_url


def connect(kind: str = "pooled", autocommit: bool = False) -> psycopg.Connection:
    """autocommit=True for web requests: each read stands alone, and every write block opened with
    write_tx() / conn.transaction() is a real transaction (not a savepoint inside an implicit one that
    would never be committed)."""
    return psycopg.connect(
        database_url(kind),
        row_factory=dict_row,
        prepare_threshold=None,
        connect_timeout=15,
        application_name="order-desk",
        autocommit=autocommit,
    )


@contextmanager
def write_tx(conn: psycopg.Connection, role: str, at: datetime | None = None) -> Iterator[psycopg.Connection]:
    """A transaction whose changes the audit triggers attribute to `role` (and optionally to time `at`)."""
    if role not in ROLES and role != "system":
        raise ValueError(f"unknown role {role!r}")
    with conn.transaction():
        conn.execute("select set_config('app.role', %s, true)", (role,))
        if at is not None:
            conn.execute("select set_config('app.ts', %s, true)", (at.isoformat(),))
        yield conn
