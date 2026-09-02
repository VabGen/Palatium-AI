"""TTL deny-resume and resolve/resume compensation for mcp_tool_approval."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.intent_hitl_flow import IntentHitlFlow
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore

HITL_HMAC = "unit-test-hitl-hmac-key-32bytes!!"  # noqa: S105


def _doc() -> ContentDocument:
    return ContentDocument(
        schema_version=1,
        locale="en-US",
        title="Needs review",
        blocks=(HeadingBlock(type="heading", level=2, text="Needs review", icon=None),),
        actions=(),
        meta=DocumentMeta(confidence=0.2, requires_review=True, source_refs=()),
    )


@pytest.mark.asyncio
async def test_auto_reject_invokes_deny_resume_for_tool_approval() -> None:
    deny = AsyncMock()
    service = HitlService(InMemoryHitlCardStore(), signing_secret=HITL_HMAC)
    service.bind_deny_resume(deny)
    card = await service.create_tool_approval_card(
        thread_id="th-1",
        task_id="task-1",
        server_name="edms",
        tool_name="search_documents",
        side_effect="read",
        risk_score=0.9,
        argument_preview="q=x",
        owner_user_id="owner",
        org_id="org-1",
    )
    # Force low-risk path so timeout policy auto-rejects (not escalate).
    low = card.model_copy(
        update={
            "risk_score": 0.2,
            "expires_at": datetime.now(UTC) - timedelta(seconds=1),
        }
    )
    await service._store.save(low)
    closed = await service._expire_card(low, now=datetime.now(UTC))
    assert closed.status == "auto_rejected"
    assert closed.resolved_action_id == "reject"
    deny.deny_tool_interrupt.assert_awaited_once()
    kwargs = deny.deny_tool_interrupt.await_args.kwargs
    assert kwargs["thread_id"] == "th-1"
    assert kwargs["task_id"] == "task-1"
    assert kwargs["card_id"] == card.card_id


@pytest.mark.asyncio
async def test_dead_letter_invokes_deny_resume_for_tool_approval() -> None:
    deny = AsyncMock()
    service = HitlService(InMemoryHitlCardStore(), signing_secret=HITL_HMAC)
    service.bind_deny_resume(deny)
    card = await service.create_tool_approval_card(
        thread_id="th-2",
        task_id="task-2",
        server_name="edms",
        tool_name="archive_document",
        side_effect="write",
        risk_score=0.9,
        argument_preview="document_id=X",
        owner_user_id="owner",
        org_id="org-1",
    )
    escalated = card.model_copy(
        update={
            "status": "escalated",
            "expires_at": datetime.now(UTC) - timedelta(seconds=1),
        }
    )
    await service._store.save(escalated)
    closed = await service._dead_letter_escalated(escalated, now=datetime.now(UTC))
    assert closed.status == "dead_letter"
    assert closed.resolved_action_id == "reject"
    deny.deny_tool_interrupt.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_reject_quality_card_skips_deny_resume() -> None:
    deny = AsyncMock()
    service = HitlService(InMemoryHitlCardStore(), signing_secret=HITL_HMAC)
    service.bind_deny_resume(deny)
    card = await service.create_review_card(
        thread_id="th-3",
        task_id="task-3",
        document=_doc(),
        confidence=0.2,
        owner_user_id="owner",
        org_id="org-1",
    )
    low = card.model_copy(
        update={
            "risk_score": 0.2,
            "expires_at": datetime.now(UTC) - timedelta(seconds=1),
        }
    )
    await service._store.save(low)
    closed = await service._expire_card(low, now=datetime.now(UTC))
    assert closed.status == "auto_rejected"
    deny.deny_tool_interrupt.assert_not_awaited()


@pytest.mark.asyncio
async def test_system_deny_skips_when_no_interrupt() -> None:
    graph = SimpleNamespace(
        aget_state=AsyncMock(side_effect=ValueError("no checkpoint")),
        ainvoke=AsyncMock(),
    )
    flow = IntentHitlFlow(
        graph_runner=SimpleNamespace(graph=graph, turn_hop_budget_ms=60_000),
        session_service=SimpleNamespace(touch_session=AsyncMock()),
        hitl_service=SimpleNamespace(),
        kill_switch=SimpleNamespace(),
        cost_budget=SimpleNamespace(),
        process_turn=AsyncMock(),
    )
    await flow.system_deny_tool_interrupt(
        thread_id="th",
        task_id="task",
        card_id="card",
        reason="ttl",
    )
    graph.ainvoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_resume_failure_compensates_with_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    """After resolve, resume failure must call deny_tool_interrupt (fail closed)."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from pydantic import SecretStr

    from palatium_ai.core.config.security import SecurityConfig
    from palatium_ai.presentation.api.routers import hitl as hitl_router
    from palatium_ai.presentation.middleware.auth import AuthMiddleware
    from palatium_ai.presentation.security.jwt import JwtTokenService

    security = SecurityConfig(
        auth_enabled=True,
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
    tokens = JwtTokenService(security)
    hitl_service = HitlService(InMemoryHitlCardStore(), signing_secret=HITL_HMAC)
    deny = AsyncMock()
    intent_service = SimpleNamespace(
        resume_after_tool_approval=AsyncMock(side_effect=RuntimeError("checkpoint boom")),
        deny_tool_interrupt=deny,
        process_hitl_choice=AsyncMock(),
        revise_after_quality_reject=AsyncMock(),
        acknowledge_quality_approve=AsyncMock(),
    )
    resources = SimpleNamespace(
        hitl_service=hitl_service,
        intent_service=intent_service,
        session_service=SimpleNamespace(),
    )
    monkeypatch.setattr(hitl_router, "get_app_resources", lambda _app: resources)
    monkeypatch.setattr(
        hitl_router,
        "load_session_for_principal",
        AsyncMock(return_value=SimpleNamespace(user_id="owner", thread_id="th")),
    )

    app = FastAPI()
    app.state.security_config = security
    app.state.token_service = tokens
    app.include_router(hitl_router.router, prefix="/api/hitl")
    app.add_middleware(AuthMiddleware, security=security, token_service=tokens)
    client = TestClient(app, raise_server_exceptions=False)

    card = await hitl_service.create_tool_approval_card(
        thread_id="th",
        task_id="task",
        server_name="edms",
        tool_name="archive_document",
        side_effect="write",
        risk_score=0.9,
        argument_preview="x",
        owner_user_id="owner",
        org_id="org-1",
    )
    # Lower step-up: disable if needed
    hitl_service._step_up_required = False
    option = next(opt for opt in card.options if opt.action_id == "approve")
    token, _ = tokens.issue_dev_token(subject="owner", roles=(), org_id="org-1")
    response = client.post(
        f"/api/hitl/{card.card_id}/respond",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "action_id": "approve",
            "action_token": option.action_token,
            "idempotency_key": "idem-comp-01",
        },
    )
    assert intent_service.resume_after_tool_approval.await_count == 1, response.text
    deny.assert_awaited_once()
    assert deny.await_args.kwargs["card_id"] == card.card_id
    stored = await hitl_service.get_card(card.card_id)
    assert stored is not None and stored.status == "resolved"
    assert response.status_code == 500
