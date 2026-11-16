# tests/integration/conftest.py

"""Integration test fixtures — opt-in when external services are available."""

from __future__ import annotations

import os

import pytest

from tests.support.database import database_url_or_skip, require_database_enabled

# The gate lives in ``tests/support/database.py`` because ``tests/perf`` (the pgvector latency
# eval) must apply the same "this job owns a database" rule. Kept under this name: the CI
# contract tests (``tests/unit/test_ci_integration_db_job.py``) assert on it directly.
_require_database_enabled = require_database_enabled


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: graph/service integration (no live LLM)")


@pytest.fixture(scope="session")
def database_url() -> str | None:
    return os.environ.get("DATABASE_URL")


@pytest.fixture()
def requires_database(database_url: str | None) -> str:
    if database_url:
        return database_url
    return database_url_or_skip(owner="tests/integration")


@pytest.fixture(scope="session")
def neo4j_credentials() -> tuple[str, str, str] | None:
    uri = os.environ.get("GRAPHITI_NEO4J_URI")
    user = os.environ.get("GRAPHITI_NEO4J_USER", "neo4j")
    password = os.environ.get("GRAPHITI_NEO4J_PASSWORD")
    if not uri or not password:
        return None
    return uri, user, password


@pytest.fixture()
def requires_neo4j(neo4j_credentials: tuple[str, str, str] | None) -> tuple[str, str, str]:
    if neo4j_credentials is None:
        pytest.skip("GRAPHITI_NEO4J_URI/PASSWORD not set — skip Neo4j integration")
    try:
        import neo4j  # noqa: F401
    except ImportError:
        pytest.skip("neo4j driver not installed — uv sync --frozen")
    return neo4j_credentials
