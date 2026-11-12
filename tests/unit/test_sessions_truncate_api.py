"""Edit rewind API: missing session row must not 404 (client-minted threads)."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.presentation.api.routers import sessions as sessions_router
from palatium_ai.presentation.security.principal import AuthPrincipal


def _principal_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    request.state.principal = AuthPrincipal(subject="user-1", roles=frozenset())
    return call_next(request)


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    ensure = AsyncMock(return_value=SimpleNamespace(thread_id="thread-fresh"))
    timeline = SimpleNamespace(truncate_dialog_turns=AsyncMock(return_value=3))
    monkeypatch.setattr(sessions_router, "ensure_session_for_principal", ensure)
    monkeypatch.setattr(
        sessions_router,
        "get_app_resources",
        lambda _app: SimpleNamespace(
            session_service=SimpleNamespace(),
            session_timeline_service=timeline,
        ),
    )

    app = FastAPI()
    app.state.security_config = SecurityConfig(
        auth_enabled=True,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("truncate-unit-secret-min-32chars!!"),
        jwks_url=None,
        cors_origins="http://127.0.0.1:8000",
        api_rate_limit=100,
        api_rate_limit_window_seconds=60,
        admin_roles="admin",
        hitl_signing_secret=SecretStr("truncate-unit-hitl-key-32bytes!!!"),
    )
    app.include_router(sessions_router.router, prefix="/api/sessions")
    app.middleware("http")(_principal_middleware)
    client = TestClient(app)
    client.ensure = ensure  # type: ignore[attr-defined]
    client.timeline = timeline  # type: ignore[attr-defined]
    return client


def test_truncate_materialises_session_then_rewinds(client: TestClient) -> None:
    response = client.post("/api/sessions/thread-fresh/turns/truncate", json={"keep": 1})

    assert response.status_code == 200
    assert response.json() == {"deleted": 3, "keep": 1}
    client.ensure.assert_awaited_once()  # type: ignore[attr-defined]
    assert client.ensure.await_args.kwargs["thread_id"] == "thread-fresh"  # type: ignore[attr-defined]
    assert client.ensure.await_args.kwargs["last_operation"] == "truncate_turns"  # type: ignore[attr-defined]
    client.timeline.truncate_dialog_turns.assert_awaited_once_with(  # type: ignore[attr-defined]
        thread_id="thread-fresh",
        keep=1,
    )
