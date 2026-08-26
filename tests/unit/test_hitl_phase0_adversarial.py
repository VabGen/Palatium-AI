"""HITL adversarial drills: IDOR, token-not-in-payload, manager resolve path."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient
from pydantic import SecretStr

from palatium_ai.application.services.hitl_service import HitlCardGoneError, HitlService
from palatium_ai.application.services.intent_service import _assistant_turn_payload
from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock
from palatium_ai.domain.hitl.cards import HITLResolveRequest
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.presentation.api.routers import hitl as hitl_router
from palatium_ai.presentation.middleware.auth import AuthMiddleware
from palatium_ai.presentation.security.jwt import JwtTokenService

HITL_HMAC = "unit-test-hitl-hmac-key-32bytes!!"  # noqa: S105


def _security(*, auth_enabled: bool = True) -> SecurityConfig:
    return SecurityConfig(
        auth_enabled=auth_enabled,
        jwt_algorithm="HS256",
        jwt_secret=SecretStr("unit-test-secret-min-32-chars!!!"),
        jwks_url=None,
        cors_origins="http://127.0.0.1:8000",
        api_rate_limit=100,
        api_rate_limit_window_seconds=60,
        admin_roles="admin",
        manager_roles="manager,admin",
        hitl_signing_secret=SecretStr(HITL_HMAC),
    )


def _doc() -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Review",
        blocks=(HeadingBlock(type="heading", level=2, text="Review", icon=None),),
        actions=(),
        meta=DocumentMeta(confidence=0.3, requires_review=True, source_refs=()),
    )


def _client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    owner_user_id: str = "user-owner",
    deny_foreign: bool = True,
) -> tuple[TestClient, HitlService, JwtTokenService]:
    security = _security()
    tokens = JwtTokenService(security)
    hitl_service = HitlService(InMemoryHitlCardStore(), signing_secret=HITL_HMAC)

    async def _load_session(**kwargs: object) -> SimpleNamespace:
        principal = kwargs.get("principal")
        subject = getattr(principal, "subject", None)
        if deny_foreign and subject not in {owner_user_id, "manager-1", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not allowed to access this session",
            )
        return SimpleNamespace(user_id=owner_user_id, thread_id="th-owner")

    monkeypatch.setattr(hitl_router, "load_session_for_principal", _load_session)

    intent_service = SimpleNamespace(
        revise_after_quality_reject=AsyncMock(),
        acknowledge_quality_approve=AsyncMock(),
        resume_after_tool_approval=AsyncMock(
            return_value=FormatterTaskResult(
                task_id="t1",
                agent_role="formatter",
                status="success",
                confidence=0.9,
                requires_review=False,
                output=_doc(),
            )
        ),
        process_hitl_choice=AsyncMock(
            return_value=FormatterTaskResult(
                task_id="t1",
                agent_role="formatter",
                status="success",
                confidence=0.9,
                requires_review=False,
                output=_doc(),
            )
        ),
    )
    resources = SimpleNamespace(
        hitl_service=hitl_service,
        intent_service=intent_service,
        session_service=SimpleNamespace(),
    )
    monkeypatch.setattr(hitl_router, "get_app_resources", lambda _app: resources)

    app = FastAPI()
    app.state.security_config = security
    app.state.token_service = tokens
    app.include_router(hitl_router.router, prefix="/api/hitl")
    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    return TestClient(app), hitl_service, tokens


def _bearer(tokens: JwtTokenService, *, sub: str, roles: tuple[str, ...] = ()) -> dict[str, str]:
    token, _ttl = tokens.issue_dev_token(subject=sub, roles=roles, org_id="org-1")
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_hitl_idor_foreign_user_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    client, hitl_service, tokens = _client(monkeypatch)
    card = await hitl_service.create_review_card(
        thread_id="th-owner",
        task_id="task-1",
        document=_doc(),
        confidence=0.3,
    )
    foreign = _bearer(tokens, sub="user-attacker")
    get_resp = client.get(f"/api/hitl/{card.card_id}", headers=foreign)
    assert get_resp.status_code == 403
    approve = next(opt for opt in card.options if opt.action_id == "approve")
    post_resp = client.post(
        f"/api/hitl/{card.card_id}/respond",
        headers=foreign,
        json={
            "action_id": "approve",
            "action_token": approve.action_token,
            "idempotency_key": "idem-idor-0001",
        },
    )
    assert post_resp.status_code == 403


@pytest.mark.asyncio
async def test_dialog_payload_strips_action_tokens() -> None:
    service = HitlService(InMemoryHitlCardStore(), signing_secret=HITL_HMAC)
    card = await service.create_review_card(
        thread_id="th-1",
        task_id="task-1",
        document=_doc(),
        confidence=0.3,
    )
    assert all(len(opt.action_token) >= 32 for opt in card.options)
    result = FormatterTaskResult(
        task_id="task-1",
        agent_role="formatter",
        status="partial",
        confidence=0.3,
        requires_review=True,
        output=_doc(),
        hitl_cards=(card,),
    )
    payload = _assistant_turn_payload(result)
    assert payload is not None
    cards = payload["hitl_cards"]
    assert isinstance(cards, list) and cards
    for opt in cards[0]["options"]:
        assert opt["action_token"] == ""


@pytest.mark.asyncio
async def test_manager_resolve_endpoint_for_escalated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, hitl_service, tokens = _client(monkeypatch)
    card = await hitl_service.create_tool_approval_card(
        thread_id="th-owner",
        task_id="task-mcp",
        server_name="edms",
        tool_name="search_documents",
        side_effect="write",
        risk_score=0.9,
        argument_preview="q=x",
    )
    expired = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
    await hitl_service._store.save(expired)
    with pytest.raises(HitlCardGoneError):
        await hitl_service.resolve(
            card.card_id,
            HITLResolveRequest(
                action_id="approve",
                action_token=card.options[0].action_token,
                idempotency_key="idem-user-late-01",
            ),
            actor_subject="user-owner",
        )
    escalated = await hitl_service.get_card(card.card_id)
    assert escalated is not None and escalated.status == "escalated"
    option = next(opt for opt in escalated.options if opt.action_id == "approve")
    manager = _bearer(tokens, sub="manager-1", roles=("manager",))
    response = client.post(
        f"/api/hitl/{card.card_id}/manager-resolve",
        headers=manager,
        json={
            "action_id": "approve",
            "action_token": option.action_token,
            "idempotency_key": "idem-mgr-api-01",
        },
    )
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    assert body["resolve"]["card"]["status"] == "resolved"
    assert body["resumed"] is not None


@pytest.mark.asyncio
async def test_step_up_challenge_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, hitl_service, tokens = _client(monkeypatch)
    # Force step-up on this service instance.
    hitl_service._step_up_required = True
    card = await hitl_service.create_tool_approval_card(
        thread_id="th-owner",
        task_id="task-mcp-su",
        server_name="edms",
        tool_name="write_doc",
        side_effect="write",
        risk_score=0.9,
        argument_preview="q=x",
        owner_user_id="user-owner",
        org_id="org-1",
    )
    owner = _bearer(tokens, sub="user-owner")
    challenge = client.post(
        f"/api/hitl/{card.card_id}/step-up-challenge",
        headers=owner,
        json={},
    )
    assert challenge.status_code == 200
    body = challenge.json()
    assert body["required"] is True
    assert body["assertion"]
    option = next(opt for opt in card.options if opt.action_id == "approve")
    respond = client.post(
        f"/api/hitl/{card.card_id}/respond",
        headers=owner,
        json={
            "action_id": "approve",
            "action_token": option.action_token,
            "idempotency_key": "idem-stepup-api-01",
            "step_up_assertion": body["assertion"],
        },
    )
    assert respond.status_code == 200
    assert respond.json()["resolve"]["card"]["status"] == "resolved"


@pytest.mark.asyncio
async def test_escalated_queue_redacts_and_scopes_org(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, hitl_service, tokens = _client(monkeypatch)
    card_a = await hitl_service.create_tool_approval_card(
        thread_id="th-owner",
        task_id="task-a",
        server_name="edms",
        tool_name="search_documents",
        side_effect="write",
        risk_score=0.9,
        argument_preview="q=a",
        owner_user_id="user-owner",
        org_id="org-1",
    )
    card_b = await hitl_service.create_tool_approval_card(
        thread_id="th-owner",
        task_id="task-b",
        server_name="edms",
        tool_name="search_documents",
        side_effect="write",
        risk_score=0.9,
        argument_preview="q=b",
        owner_user_id="user-owner",
        org_id="org-2",
    )
    for card in (card_a, card_b):
        expired = card.model_copy(update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        await hitl_service._store.save(expired)
    await hitl_service.sweep_expired()

    manager = _bearer(tokens, sub="manager-1", roles=("manager",))
    response = client.get("/api/hitl/queue/escalated", headers=manager)
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["card_id"] == card_a.card_id
    assert all(opt["action_token"] == "" for opt in items[0]["options"])

    get_resp = client.get(f"/api/hitl/{card_a.card_id}", headers=manager)
    assert get_resp.status_code == 200
    live = get_resp.json()
    assert live["status"] == "escalated"
    assert all(len(opt["action_token"]) >= 32 for opt in live["options"])
