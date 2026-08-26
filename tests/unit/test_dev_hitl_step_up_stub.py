# tests/unit/test_dev_hitl_step_up_stub.py

"""Development IdP step-up stub + mint-tool-approval seam."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import jwt
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.presentation.api.routers import auth, hitl
from palatium_ai.presentation.middleware.auth import AuthMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService
from palatium_ai.presentation.security.principal import AuthPrincipal


def _security() -> SecurityConfig:
    return SecurityConfig(
        auth_enabled=True,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("dev-hitl-step-up-secret-32bytes!!"),
        cors_origins="http://127.0.0.1:8000",
        hitl_step_up_method="idp_acr",
        hitl_step_up_required=True,
    )


def test_effective_hitl_step_up_required_override() -> None:
    sec = _security()
    assert sec.effective_hitl_step_up_required("development") is True
    sec2 = SecurityConfig(
        auth_enabled=True,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("dev-hitl-step-up-secret-32bytes!!"),
        cors_origins="http://127.0.0.1:8000",
        hitl_step_up_required=None,
    )
    assert sec2.effective_hitl_step_up_required("development") is False
    assert sec2.effective_hitl_step_up_required("staging") is True


def test_dev_hitl_step_up_returns_json_assertion() -> None:
    security = _security()
    tokens = JwtTokenService(security)
    app = FastAPI()
    app.state.settings = SimpleNamespace(app=SimpleNamespace(environment="development"), security=security)
    app.state.token_service = tokens
    app.state.security_config = security
    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    app.include_router(auth.router, prefix="/api/auth")
    client = TestClient(app)
    response = client.get(
        "/api/auth/dev-hitl-step-up",
        params={
            "card_id": "card-1",
            "subject": "user-a",
            "challenge": "nonce",
            "required_acr": "urn:palatium:acr:step-up",
            "card_claim": "hitl_card_id",
            "method": "idp_acr",
        },
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    body = response.json()
    assertion = body["assertion"]
    claims = jwt.decode(
        assertion,
        security.jwt_secret.get_secret_value(),  # type: ignore[union-attr]
        algorithms=["HS256"],
    )
    assert claims["sub"] == "user-a"
    assert claims["hitl_card_id"] == "card-1"
    assert claims["acr"] == "urn:palatium:acr:step-up"


def test_dev_hitl_step_up_hidden_outside_development() -> None:
    security = _security()
    tokens = JwtTokenService(security)
    app = FastAPI()
    app.state.settings = SimpleNamespace(app=SimpleNamespace(environment="staging"), security=security)
    app.state.token_service = tokens
    app.state.security_config = security
    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    app.include_router(auth.router, prefix="/api/auth")
    client = TestClient(app)
    response = client.get(
        "/api/auth/dev-hitl-step-up",
        params={"card_id": "card-1", "subject": "user-a"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_dev_mint_tool_approval_development_only(monkeypatch: pytest.MonkeyPatch) -> None:
    security = _security()
    tokens = JwtTokenService(security)
    minted = AsyncMock(
        return_value=HITLCardView.model_validate(
            {
                "card_id": "c1",
                "thread_id": "th-1",
                "task_id": "t1",
                "purpose": "mcp_tool_approval",
                "title": "Approve",
                "body": "x",
                "options": [
                    {
                        "action_id": "approve",
                        "label": "Approve",
                        "kind": "approve",
                        "style": "primary",
                        "action_token": "tok",
                    }
                ],
                "risk_score": 0.85,
                "status": "pending",
                "created_at": "2026-01-01T00:00:00Z",
                "expires_at": "2026-01-01T01:00:00Z",
            }
        )
    )
    session = SimpleNamespace(thread_id="th-1", user_id="user-a")
    app = FastAPI()
    app.state.settings = SimpleNamespace(app=SimpleNamespace(environment="development"), security=security)
    app.state.token_service = tokens
    app.state.security_config = security
    app.state.resources = SimpleNamespace(
        hitl_service=SimpleNamespace(create_tool_approval_card=minted),
        session_service=SimpleNamespace(get_session=AsyncMock(return_value=session)),
    )
    monkeypatch.setattr(
        "palatium_ai.presentation.api.routers.hitl.load_session_for_principal",
        AsyncMock(return_value=session),
    )
    monkeypatch.setattr(
        "palatium_ai.presentation.api.routers.hitl.get_app_resources",
        lambda _app: app.state.resources,
    )
    monkeypatch.setattr(
        "palatium_ai.presentation.api.routers.hitl.get_principal",
        lambda _req: AuthPrincipal(subject="user-a", roles=frozenset(), org_id="org-1"),
    )
    app.include_router(hitl.router, prefix="/api/hitl")
    client = TestClient(app)
    response = client.post(
        "/api/hitl/dev/mint-tool-approval",
        json={"thread_id": "th-1"},
        headers={"Authorization": f"Bearer {tokens.issue_dev_token(subject='user-a')[0]}"},
    )
    assert response.status_code == 200
    assert response.json()["card_id"] == "c1"
    minted.assert_awaited()


def test_snapshot_awaits_resume_contract() -> None:
    from palatium_ai.application.services.intent_service import _snapshot_awaits_resume

    assert _snapshot_awaits_resume(SimpleNamespace(interrupts=(), tasks=(), values={})) is False
    assert _snapshot_awaits_resume(SimpleNamespace(interrupts=("x",), tasks=(), values={})) is True
    assert (
        _snapshot_awaits_resume(
            SimpleNamespace(
                interrupts=(),
                tasks=(SimpleNamespace(interrupts=("pause",)),),
                values={},
            )
        )
        is True
    )
    assert (
        _snapshot_awaits_resume(SimpleNamespace(interrupts=(), tasks=(), values={"__interrupt__": ("pause",)})) is True
    )
