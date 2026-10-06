"""Sessions list pagination bounds — the ceiling comes from `core/types`, not a literal (080).

A list endpoint without an upper bound is an unbounded query, so the bound is part of the
API contract: it is asserted against `PAGE_LIMIT_MAX`/`PAGE_LIMIT_DEFAULT` from the single
owner module rather than against a copy of the numbers, so raising the ceiling stays a
one-line change (010, 080).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.core.types.pagination import PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MAX
from palatium_ai.presentation.api.routers import sessions as sessions_router
from palatium_ai.presentation.security.principal import AuthPrincipal


def _principal_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Stand in for AuthMiddleware: the router reads `request.state.principal` directly."""
    request.state.principal = AuthPrincipal(subject="user-1", roles=frozenset())
    return call_next(request)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = FastAPI()
    app.state.security_config = SecurityConfig(
        auth_enabled=True,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("pagination-unit-secret-min-32ch!!!"),
        jwks_url=None,
        cors_origins="http://127.0.0.1:8000",
        api_rate_limit=100,
        api_rate_limit_window_seconds=60,
        admin_roles="admin",
        hitl_signing_secret=SecretStr("pagination-unit-hitl-key-32bytes!"),
    )
    monkeypatch.setattr(
        sessions_router,
        "get_app_resources",
        lambda _app: SimpleNamespace(session_service=SimpleNamespace(list_sessions=AsyncMock(return_value=[]))),
    )
    app.include_router(sessions_router.router, prefix="/api/sessions")
    app.middleware("http")(_principal_middleware)
    return TestClient(app)


def test_default_page_uses_the_declared_defaults(client: TestClient) -> None:
    response = client.get("/api/sessions/")

    assert response.status_code == 200
    assert response.json()["limit"] == PAGE_LIMIT_DEFAULT
    assert response.json()["offset"] == 0


def test_ceiling_is_accepted(client: TestClient) -> None:
    response = client.get("/api/sessions/", params={"limit": PAGE_LIMIT_MAX})

    assert response.status_code == 200
    assert response.json()["limit"] == PAGE_LIMIT_MAX


def test_above_the_ceiling_is_rejected(client: TestClient) -> None:
    response = client.get("/api/sessions/", params={"limit": PAGE_LIMIT_MAX + 1})

    assert response.status_code == 422, "a page larger than PAGE_LIMIT_MAX must not reach the database"


@pytest.mark.parametrize("limit", (0, -1))
def test_non_positive_limit_is_rejected(client: TestClient, limit: int) -> None:
    response = client.get("/api/sessions/", params={"limit": limit})

    assert response.status_code == 422


def test_negative_offset_is_rejected(client: TestClient) -> None:
    response = client.get("/api/sessions/", params={"offset": -1})

    assert response.status_code == 422
