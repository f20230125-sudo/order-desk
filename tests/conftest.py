import os

import pytest

from backend.config import database_url


def _test_url() -> str | None:
    try:
        return database_url("test")
    except RuntimeError:
        return None


@pytest.fixture(scope="session")
def migrated_db():
    """A migrated test database. Skips the test if DATABASE_URL_TEST is not set."""
    if not _test_url():
        pytest.skip("DATABASE_URL_TEST not set")
    if "neon.tech" in _test_url() and "test" not in os.environ.get("ORDER_DESK_ALLOW_NEON_TESTS", ""):
        # The tests empty every table; refuse a Neon URL unless it is explicitly the test branch.
        pytest.skip("set ORDER_DESK_ALLOW_NEON_TESTS=test to run against a Neon test branch")
    from backend.db.conn import connect
    from backend.db.migrate import migrate

    with connect("test") as conn:
        migrate(conn)
    return True


TABLES = (
    "event, rate_limit, pending_upload, discrepancy, check_run, document, serial, shipment_line, shipment, "
    "vendor_confirmation_line, vendor_confirmation, purchase_order_line, purchase_order, customer_order_line, "
    "customer_order, product, party"
)


@pytest.fixture
def db(migrated_db):
    """A connection to an emptied test database."""
    from backend.db.conn import connect

    with connect("test") as conn:
        conn.execute(f"truncate {TABLES} restart identity cascade")
        conn.commit()
        yield conn
