# tests/unit/test_api_auth_week0.py

"""Week 0: JWT auth, CORS config, rate limit, ownership helpers."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr

from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.presentation.api.routers import auth as auth_router
from palatium_ai.presentation.middleware.auth import AuthMiddleware
from palatium_ai.presentation.middleware.rate_limit import RateLimitMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService, JwtValidationError
from palatium_ai.presentation.security.ownership import assert_session_access
from palatium_ai.presentation.security.principal import AuthPrincipal


def _hs_security(**overrides: object) -> SecurityConfig:
    data: dict[str, object] = {
        "auth_enabled": True,
        "jwt_algorithm": "HS256",
        "jwt_secret": SecretStr("unit-test-secret-min-32-chars!!!"),
        "jwks_url": None,
        "cors_origins": "http://127.0.0.1:8000",
        "api_rate_limit": 3,
        "api_rate_limit_window_seconds": 60,
        "admin_roles": "admin",
    }
    data.update(overrides)
    return SecurityConfig(**data)  # type: ignore[arg-type]


def test_jwt_roundtrip_and_reject_tampered() -> None:
    security = _hs_security()
    tokens = JwtTokenService(security)
    raw, ttl = tokens.issue_dev_token(subject="user-1", org_id="org-a", roles=("admin",))
    assert ttl > 0
    principal = tokens.verify_bearer(raw)
    assert principal.subject == "user-1"
    assert principal.org_id == "org-a"
    assert "admin" in principal.roles

    with pytest.raises(JwtValidationError):
        tokens.verify_bearer(raw + "x")


def test_require_auth_material_hs_without_secret() -> None:
    security = _hs_security(jwt_secret=None)
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        security.require_auth_material()


def test_cors_origin_list_no_wildcard() -> None:
    security = _hs_security(cors_origins="http://a.example, http://b.example")
    assert security.cors_origin_list == ("http://a.example", "http://b.example")


def test_cors_wildcard_rejected() -> None:
    with pytest.raises(Exception, match="wildcard"):
        _hs_security(cors_origins="*")
    with pytest.raises(Exception, match="wildcard"):
        _hs_security(cors_origins="https://evil.example, *")


def test_auth_middleware_rejects_anonymous_api() -> None:
    security = _hs_security()
    tokens = JwtTokenService(security)
    app = FastAPI()
    app.state.security_config = security
    app.state.token_service = tokens

    @app.get("/api/secure")
    async def secure(request: Request) -> dict[str, str]:
        principal = request.state.principal
        return {"sub": principal.subject}

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    client = TestClient(app)

    assert client.get("/health").status_code == 200
    assert client.get("/api/secure").status_code == 401

    token, _ = tokens.issue_dev_token(subject="user-42")
    ok = client.get("/api/secure", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json() == {"sub": "user-42"}


def test_rate_limit_on_process_path() -> None:
    app = FastAPI()

    @app.post("/api/intents/process")
    async def process() -> dict[str, str]:
        return {"ok": "1"}

    app.add_middleware(RateLimitMiddleware, limit=2, window_seconds=60)
    client = TestClient(app)
    assert client.post("/api/intents/process").status_code == 200
    assert client.post("/api/intents/process").status_code == 200
    blocked = client.post("/api/intents/process")
    assert blocked.status_code == 429


def test_session_ownership_blocks_foreign_user() -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(security_config=_hs_security())))
    owner = AuthPrincipal(subject="user-a", roles=frozenset())
    stranger = AuthPrincipal(subject="user-b", roles=frozenset())
    session = SimpleNamespace(user_id="user-a")

    assert assert_session_access(request=request, principal=owner, session=session) is session
    with pytest.raises(HTTPException) as exc:
        assert_session_access(request=request, principal=stranger, session=session)
    assert exc.value.status_code == 403

    admin = AuthPrincipal(subject="ops", roles=frozenset({"admin"}))
    assert assert_session_access(request=request, principal=admin, session=session) is session


def test_auth_disabled_does_not_grant_admin() -> None:
    security = _hs_security(auth_enabled=False)
    tokens = JwtTokenService(security)
    app = FastAPI()

    @app.get("/api/secure")
    async def secure(request: Request) -> dict[str, object]:
        principal = request.state.principal
        return {"sub": principal.subject, "admin": "admin" in principal.roles}

    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    client = TestClient(app)
    payload = client.get("/api/secure").json()
    assert payload["sub"] == "anonymous"
    assert payload["admin"] is False


def test_metrics_requires_auth_when_not_public() -> None:
    security = _hs_security()
    tokens = JwtTokenService(security)
    app = FastAPI()

    @app.get("/metrics")
    async def metrics() -> dict[str, str]:
        return {"ok": "1"}

    app.add_middleware(
        AuthMiddleware,
        security=security,
        token_service=tokens,
        metrics_public=False,
    )
    client = TestClient(app)
    assert client.get("/metrics").status_code == 401
    token, _ = tokens.issue_dev_token(subject="scraper")
    assert client.get("/metrics", headers={"Authorization": f"Bearer {token}"}).status_code == 200


def test_dev_token_endpoint_strips_admin_role() -> None:
    security = _hs_security()
    tokens = JwtTokenService(security)
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        app=SimpleNamespace(environment="development"),
        security=security,
    )
    app.state.token_service = tokens
    app.include_router(auth_router.router, prefix="/api/auth")
    client = TestClient(app)
    response = client.post(
        "/api/auth/dev-token",
        json={"user_id": "user-1", "roles": ["admin", "reader"]},
    )
    assert response.status_code == 200
    principal = tokens.verify_bearer(response.json()["access_token"])
    assert "admin" not in principal.roles
    assert "reader" in principal.roles
