"""Wave 5/8 presentation layer unit tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.core.observability.trace_context import resolve_trace_id, trace_id_header_name
from palatium_ai.presentation.middleware.tracing import TracingMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService
from palatium_ai.presentation.websockets import session as ws_session


def test_resolve_trace_id_from_header() -> None:
    assert resolve_trace_id(header_value="abc-123", traceparent=None) == "abc-123"


def test_resolve_trace_id_from_traceparent() -> None:
    parent = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"
    assert resolve_trace_id(header_value=None, traceparent=parent) == "4bf92f3577b34da6a3ce929d0e0e4736"


def test_resolve_trace_id_mints_when_missing() -> None:
    trace_id = resolve_trace_id(header_value=None, traceparent=None)
    assert len(trace_id) == 32


def test_tracing_middleware_echoes_trace_header() -> None:
    app = FastAPI()
    app.add_middleware(TracingMiddleware)

    @app.get("/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    client = TestClient(app)
    response = client.get("/ping", headers={trace_id_header_name(): "trace-abc"})
    assert response.status_code == 200
    assert response.headers[trace_id_header_name()] == "trace-abc"


def _security(*, auth_enabled: bool) -> SecurityConfig:
    return SecurityConfig(
        auth_enabled=auth_enabled,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("unit-test-secret-min-32-chars!!!"),
        jwks_url=None,
        cors_origins="http://127.0.0.1:8000",
        api_rate_limit=100,
        api_rate_limit_window_seconds=60,
        admin_roles="admin",
        hitl_signing_secret=SecretStr("unit-test-hitl-hmac-key-32bytes!!"),
    )


@pytest.fixture
def ws_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    security = _security(auth_enabled=True)
    app = FastAPI()
    app.state.security_config = security
    app.state.token_service = JwtTokenService(security)
    resources = SimpleNamespace(
        session_service=AsyncMock(
            return_value=SimpleNamespace(user_id="user-1", thread_id="th-1"),
        ),
    )
    monkeypatch.setattr(ws_session, "get_app_resources", lambda _app: resources)
    ws_session.register_websocket_routes(app)
    return app


def test_websocket_rejects_missing_jwt(ws_app: FastAPI) -> None:
    client = TestClient(ws_app)
    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/sessions/th-1") as websocket:
        websocket.receive_json()


def test_websocket_subscribes_with_valid_jwt(ws_app: FastAPI) -> None:
    tokens = JwtTokenService(_security(auth_enabled=True))
    token, _ = tokens.issue_dev_token(subject="user-1")
    client = TestClient(ws_app)
    with client.websocket_connect(f"/ws/sessions/th-1?token={token}") as websocket:
        payload = websocket.receive_json()
    assert payload["type"] == "session.subscribed"
    assert payload["thread_id"] == "th-1"
    assert payload["trace_id"]
