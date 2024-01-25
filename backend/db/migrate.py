"""Apply the numbered SQL files in backend/db/migrations, once each, in order.

    python -m backend.db.migrate            # the database in DATABASE_URL_UNPOOLED
    python -m backend.db.migrate --test     # the test branch in DATABASE_URL_TEST

Each file runs in its own transaction and is recorded with a checksum. Editing a file that has already
been applied is refused: write a new numbered file instead, so every database ends up the same.
An advisory lock stops two runs (say, a deploy and the nightly reset) from migrating at the same time.
"""

import hashlib
import re
import sys
from pathlib import Path

import psycopg

from backend.db.conn import connect

MIGRATIONS = Path(__file__).resolve().parent / "migrations"
NAME = re.compile(r"^(\d{3})_[a-z0-9_]+\.sql$")
LOCK_KEY = 74_210_001


class MigrationError(RuntimeError):
    pass


def migration_files() -> list[Path]:
    files = sorted(p for p in MIGRATIONS.iterdir() if p.suffix == ".sql")
    bad = [p.name for p in files if not NAME.match(p.name)]
    if bad:
        raise MigrationError(f"badly named migration files: {bad}")
    numbers = [p.name[:3] for p in files]
    if len(set(numbers)) != len(numbers):
        raise MigrationError("two migration files share a number")
    return files


def checksum(path: Path) -> str:
    # Normalise line endings so a Windows checkout and the Linux CI agree.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def migrate(conn: psycopg.Connection) -> list[str]:
    """Apply what is missing; return the names applied."""
    conn.execute(
        """create table if not exists schema_migrations (
               name text primary key, checksum text not null, applied_at timestamptz not null default now())"""
    )
    conn.commit()
    conn.execute("select pg_advisory_lock(%s)", (LOCK_KEY,))
    try:
        done = {
            r["name"]: r["checksum"] for r in conn.execute("select name, checksum from schema_migrations")
        }
        conn.commit()
        applied = []
        for path in migration_files():
            digest = checksum(path)
            if path.name in done:
                if done[path.name] != digest:
                    raise MigrationError(
                        f"{path.name} changed after it was applied; add a new migration instead"
                    )
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "insert into schema_migrations (name, checksum) values (%s, %s)", (path.name, digest)
                )
            applied.append(path.name)
        return applied
    finally:
        conn.execute("select pg_advisory_unlock(%s)", (LOCK_KEY,))
        conn.commit()


def main() -> None:
    kind = "test" if "--test" in sys.argv else "direct"
    with connect(kind) as conn:
        applied = migrate(conn)
    print("applied: " + (", ".join(applied) if applied else "nothing, already up to date"))


if __name__ == "__main__":
    main()
