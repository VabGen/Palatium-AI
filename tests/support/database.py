# tests/support/database.py

"""Fail-closed database gating shared by the Postgres test suites (075).

``PALATIUM_REQUIRE_DB=1`` turns "no ``DATABASE_URL``" from a skip into a failure. A skipped
database test is indistinguishable from a passing one in the CI summary — which is exactly
how the Postgres extract queue went untested while every job stayed green. Jobs that own a
database set this flag, so a missing or mistyped URL is loud instead of silent.

One implementation, not one per suite: ``tests/integration`` (the SQL suite) and
``tests/perf`` (the pgvector latency eval) must agree on what "the job owns a database"
means, otherwise the second suite quietly restores the skip the first one removed.
"""

from __future__ import annotations

import os

import pytest

DATABASE_URL_ENV = "DATABASE_URL"
REQUIRE_DATABASE_ENV = "PALATIUM_REQUIRE_DB"

_TRUTHY = frozenset({"1", "true", "yes"})


def require_database_enabled() -> bool:
    """Whether the current job declares that it owns a database."""
    return os.environ.get(REQUIRE_DATABASE_ENV, "").strip().lower() in _TRUTHY


def database_url_or_skip(*, owner: str) -> str:
    """Return ``DATABASE_URL``, or skip/fail depending on whether ``owner`` owns a database."""
    url = os.environ.get(DATABASE_URL_ENV, "").strip()
    if url:
        return url
    if require_database_enabled():
        pytest.fail(
            f"{DATABASE_URL_ENV} is required ({REQUIRE_DATABASE_ENV}=1): {owner} owns a database, "
            "so a missing URL must fail instead of skipping the SQL path (rule 075)"
        )
    pytest.skip(f"{DATABASE_URL_ENV} not set — {owner} needs a Postgres/pgvector cluster")
