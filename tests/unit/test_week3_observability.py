# tests/unit/test_week3_observability.py

"""Week 3: Prometheus /metrics scrape + LangSmith env wiring + HITL HMAC."""

from __future__ import annotations

import os

from datetime import UTC, datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from palatium_ai.core.config.observability import ObservabilityConfig
from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.core.observability.langsmith_env import apply_langsmith_env
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.hitl.action_tokens import mint_action_token, verify_action_token
from palatium_ai.presentation.api.routers import metrics as metrics_router
from palatium_ai.presentation.middleware.auth import AuthMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService


def test_metrics_endpoint_is_public_and_exposes_prometheus_text() -> None:
    agent_metrics.record_node_execution("formatter", "formatter_node", duration_seconds=0.01)
    security = SecurityConfig(
        auth_enabled=True,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("unit-test-secret-min-32-chars!!!"),
        cors_origins="http://127.0.0.1:8000",
    )
    tokens = JwtTokenService(security)
    app = FastAPI()
    app.include_router(metrics_router.router)
    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    client = TestClient(app)

    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.text
    assert "agent_request_duration_seconds" in body


def test_apply_langsmith_env_disables_without_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    apply_langsmith_env(
        ObservabilityConfig(
            langchain_tracing_v2=True,
            langchain_api_key=None,
            langchain_project="palatium-unit",
        )
    )
    assert os.environ["LANGCHAIN_TRACING_V2"] == "false"
    assert os.environ["LANGCHAIN_PROJECT"] == "palatium-unit"


def test_apply_langsmith_env_enables_with_real_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    apply_langsmith_env(
        ObservabilityConfig(
            langchain_tracing_v2=True,
            langchain_api_key=SecretStr("lsv2_real_test_key_not_placeholder"),
            langchain_project="palatium-unit",
        )
    )
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    assert os.environ["LANGCHAIN_API_KEY"] == "lsv2_real_test_key_not_placeholder"
    # Leave suite clean — avoid 403 spam against LangSmith from later graph tests.
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    apply_langsmith_env(
        ObservabilityConfig(
            langchain_tracing_v2=False,
            langchain_api_key=None,
            langchain_project="palatium-unit",
        )
    )


def test_hitl_action_token_roundtrip() -> None:
    expires = datetime.now(UTC) + timedelta(minutes=15)
    token = mint_action_token(
        secret="s" * 32,
        card_id="hitl_abc",
        action_id="approve",
        expires_at=expires,
        subject="user-1",
        nonce="nonce-abc123",
    )
    assert verify_action_token(
        secret="s" * 32,
        token=token,
        card_id="hitl_abc",
        action_id="approve",
        expires_at=expires,
        subject="user-1",
        nonce="nonce-abc123",
    )
    assert not verify_action_token(
        secret="s" * 32,
        token=token,
        card_id="hitl_abc",
        action_id="reject",
        expires_at=expires,
        subject="user-1",
        nonce="nonce-abc123",
    )
    assert not verify_action_token(
        secret="s" * 32,
        token=token,
        card_id="hitl_abc",
        action_id="approve",
        expires_at=expires,
        subject="user-other",
        nonce="nonce-abc123",
    )


def test_rs_auth_requires_hitl_signing_secret() -> None:
    security = SecurityConfig(
        auth_enabled=True,
        jwt_algorithm="RS256",
        jwt_secret=None,
        hitl_signing_secret=None,
        jwks_url="https://example.com/.well-known/jwks.json",
        cors_origins="http://127.0.0.1:8000",
    )
    try:
        security.require_auth_material()
        raised = False
    except RuntimeError as exc:
        raised = True
        assert "HITL_SIGNING_SECRET" in str(exc)
    assert raised
