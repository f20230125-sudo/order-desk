"""Settings read from the environment.

Locally the values come from a .env file (this repo's, or the one Uzair keeps in condo-protego/);
on Vercel they are set as project environment variables. No python-dotenv: the format is KEY=VALUE.
"""

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILES = (ROOT / ".env", ROOT.parent / "condo-protego" / ".env")

ROLES = ("sales", "ops", "finance")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
DAILY_UPLOAD_CAP_BYTES = 50 * 1024 * 1024


def _load_env_files() -> None:
    for path in ENV_FILES:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_files()


def database_url(kind: str = "pooled") -> str:
    """Connection string for the app ("pooled"), for maintenance ("direct") or for tests ("test")."""
    names = {
        "pooled": ("DATABASE_URL",),
        "direct": ("DATABASE_URL_UNPOOLED", "DATABASE_URL"),
        "test": ("DATABASE_URL_TEST",),
    }[kind]
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    raise RuntimeError(f"Set {names[0]} (see .env.example)")
