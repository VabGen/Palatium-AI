# tests/unit/test_database_gate.py

"""Contract of the shared database gate (075).

``tests/integration`` and ``tests/perf`` both skip without ``DATABASE_URL`` and both must go
red when the job that owns a database loses it. One implementation now serves both, so the
branch that decides skip-vs-fail is worth pinning on its own — the alternative is that a
refactor quietly restores the silent skip this gate exists to prevent.
"""

from __future__ import annotations

import pytest

from tests.support.database import database_url_or_skip, require_database_enabled

_DSN = "postgresql+asyncpg://postgres:test@localhost:5432/postgres"


def test_present_url_is_returned_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", _DSN)
    assert database_url_or_skip(owner="tests/unit") == _DSN


@pytest.mark.parametrize("value", ("", "   "))
def test_blank_url_counts_as_missing(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DATABASE_URL", value)
    monkeypatch.delenv("PALATIUM_REQUIRE_DB", raising=False)
    with pytest.raises(pytest.skip.Exception, match="needs a Postgres/pgvector cluster"):
        database_url_or_skip(owner="tests/unit")


def test_missing_url_fails_when_the_job_owns_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """A lost URL in the owning job must be red — a skipped SQL suite is how the queue went untested."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PALATIUM_REQUIRE_DB", "1")
    with pytest.raises(pytest.fail.Exception, match="rule 075"):
        database_url_or_skip(owner="tests/unit")


def test_missing_url_skips_when_the_job_does_not_own_a_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("PALATIUM_REQUIRE_DB", raising=False)
    with pytest.raises(pytest.skip.Exception, match="tests/unit"):
        database_url_or_skip(owner="tests/unit")


def test_flag_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PALATIUM_REQUIRE_DB", raising=False)
    assert require_database_enabled() is False
