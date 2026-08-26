"""API: quality HITL reject → revise returns resumed formatter output."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.presentation.api.routers import hitl as hitl_router
from palatium_ai.presentation.middleware.auth import AuthMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService

HITL_HMAC = "unit-test-hitl-hmac-key-32bytes!!"  # noqa: S105


def _doc(*, title: str = "Revised answer") -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title=title,
        blocks=(HeadingBlock(type="heading", level=2, text=title, icon=None),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )


def _security() -> SecurityConfig:
    return SecurityConfig(
        auth_enabled=False,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("unit-test-secret-min-32-chars!!!"),
        jwks_url=None,
        cors_origins="http://127.0.0.1:8000",
        api_rate_limit=100,
        api_rate_limit_window_seconds=60,
        admin_roles="admin",
        hitl_signing_secret=SecretStr(HITL_HMAC),
    )


@pytest.fixture
def hitl_api_client(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TestClient, HitlService, AsyncMock, AsyncMock]:
    security = _security()
    tokens = JwtTokenService(security)
    hitl_service = HitlService(InMemoryHitlCardStore(), signing_secret=HITL_HMAC)
    revise = AsyncMock(
        return_value=FormatterTaskResult(
            task_id="task-1",
            agent_role="formatter",
            status="success",
            confidence=0.9,
            requires_review=False,
            output=_doc(),
        )
    )
    acknowledge = AsyncMock()
    intent_service = SimpleNamespace(
        revise_after_quality_reject=revise,
        acknowledge_quality_approve=acknowledge,
        resume_after_tool_approval=AsyncMock(),
    )
    session_service = SimpleNamespace(
        get_session=AsyncMock(return_value=SimpleNamespace(user_id="anonymous", thread_id="th-1"))
    )
    resources = SimpleNamespace(
        hitl_service=hitl_service,
        intent_service=intent_service,
        session_service=session_service,
    )
    monkeypatch.setattr(hitl_router, "get_app_resources", lambda _app: resources)

    app = FastAPI()
    app.state.security_config = security
    app.state.token_service = tokens
    app.include_router(hitl_router.router, prefix="/api/hitl")
    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    return TestClient(app), hitl_service, revise, acknowledge


@pytest.mark.asyncio
async def test_quality_reject_respond_returns_resumed(
    hitl_api_client: tuple[TestClient, HitlService, AsyncMock, AsyncMock],
) -> None:
    client, hitl_service, revise, acknowledge = hitl_api_client
    card = await hitl_service.create_review_card(
        thread_id="th-1",
        task_id="task-1",
        document=_doc(title="Needs review"),
        confidence=0.3,
    )
    reject = next(opt for opt in card.options if opt.action_id == "reject")

    response = client.post(
        f"/api/hitl/{card.card_id}/respond",
        json={
            "action_id": "reject",
            "action_token": reject.action_token,
            "idempotency_key": "idem-quality-reject-01",
        },
    )
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["resolve"]["card"]["status"] == "resolved"
    assert payload["resolve"]["card"]["resolved_action_id"] == "reject"
    assert payload["resumed"] is not None
    assert payload["resumed"]["output"]["title"] == "Revised answer"
    revise.assert_awaited_once()
    acknowledge.assert_not_awaited()


@pytest.mark.asyncio
async def test_quality_approve_respond_acks_without_resumed(
    hitl_api_client: tuple[TestClient, HitlService, AsyncMock, AsyncMock],
) -> None:
    client, hitl_service, revise, acknowledge = hitl_api_client
    card = await hitl_service.create_review_card(
        thread_id="th-1",
        task_id="task-1",
        document=_doc(title="Needs review"),
        confidence=0.3,
    )
    approve = next(opt for opt in card.options if opt.action_id == "approve")

    response = client.post(
        f"/api/hitl/{card.card_id}/respond",
        json={
            "action_id": "approve",
            "action_token": approve.action_token,
            "idempotency_key": "idem-quality-approve-01",
        },
    )
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["resolve"]["card"]["resolved_action_id"] == "approve"
    assert payload["resumed"] is None
    revise.assert_not_awaited()
    acknowledge.assert_awaited_once()
