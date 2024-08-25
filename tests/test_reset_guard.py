"""The nightly reset refuses any database but the named one, and tolerates how secrets get pasted."""

import pytest

from backend.config import clean_setting
from backend.db.seed import _refusal

URL = "postgresql://u:p@ep-demo.c-6.us-east-2.aws.neon.tech/neondb?sslmode=require"
HOST = "ep-demo.c-6.us-east-2.aws.neon.tech"


@pytest.mark.parametrize(
    "pasted",
    [HOST, f"  {HOST}\n", f'"{HOST}"', f"ORDER_DESK_RESET_HOST={HOST}", HOST.upper(), URL],
)
def test_the_named_host_may_be_reset_however_it_was_pasted(monkeypatch, pasted):
    monkeypatch.setenv("ORDER_DESK_RESET_HOST", pasted)
    assert _refusal(URL, test=False) is None


def test_another_host_or_no_host_is_refused(monkeypatch):
    monkeypatch.setenv("ORDER_DESK_RESET_HOST", "ep-other.c-6.us-east-2.aws.neon.tech")
    assert "is not this database's host" in _refusal(URL, test=False)
    monkeypatch.delenv("ORDER_DESK_RESET_HOST")
    assert "set ORDER_DESK_RESET_HOST" in _refusal(URL, test=False)


def test_a_pasted_env_line_reads_as_its_value():
    assert clean_setting(f'DATABASE_URL_UNPOOLED="{URL}"\n', "DATABASE_URL_UNPOOLED") == URL
