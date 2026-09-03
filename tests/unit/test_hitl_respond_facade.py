"""Wave 8: HITL respond facade orchestration (presentation logic in application layer)."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption, HITLResolveRequest, HITLResolveResult


def _card(*, purpose: str = "mcp_tool_approval") -> HITLCardView:
    now = datetime(2099, 1, 1, tzinfo=UTC)
    return HITLCardView(
        card_id="card-1",
        thread_id="th-1",
        task_id="task-1",
        purpose=purpose,  # type: ignore[arg-type]
        title="Approve MCP",
        body=None,
        options=(
            HITLOption(
                action_id="approve",
                label="Approve",
                kind="custom",
                style="primary",
                action_token="t" * 32,
            ),
        ),
        risk_score=0.8,
        status="pending",
        created_at=now,
        expires_at=now,
        owner_user_id="user-1",
        org_id="org-1",
    )


def _resolve_result(card: HITLCardView, *, replayed: bool = False) -> HITLResolveResult:
    return HITLResolveResult(card=card, replayed=replayed, message="ok")


def _formatter_result() -> FormatterTaskResult:
    doc = ContentDocument(
        schema_version=1,
        locale="ru-RU",
        title="Done",
        blocks=(HeadingBlock(type="heading", level=2, text="Done", icon=None),),
        actions=(),
        meta=DocumentMeta(confidence=0.9, requires_review=False, source_refs=()),
    )
    return FormatterTaskResult(
        task_id="task-1",
        agent_role="formatter",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=doc,
    )


@pytest.mark.asyncio
async def test_respond_skips_resume_when_replayed() -> None:
    card = _card()
    hitl = AsyncMock()
    hitl.resolve.return_value = _resolve_result(card, replayed=True)
    hitl.get_card.return_value = card
    intent = AsyncMock()
    intent.resume_after_tool_approval = AsyncMock()
    facade = HitlRespondFacade(hitl_service=hitl, intent_service=intent)

    body = HITLResolveRequest(action_id="approve", action_token="t" * 32, idempotency_key="idem-1234")
    outcome = await facade.respond(
        "card-1",
        body,
        actor_subject="user-1",
        actor_org_id="org-1",
        is_admin=False,
    )

    assert outcome.resolve.replayed is True
    assert outcome.resumed is None
    intent.resume_after_tool_approval.assert_not_awaited()


@pytest.mark.asyncio
async def test_respond_doc_ingest_skips_graph_resume() -> None:
    card = _card(purpose="mcp_tool_approval")
    card = card.model_copy(update={"task_id": "doc-ingest-abc123"})
    hitl = AsyncMock()
    hitl.resolve.return_value = _resolve_result(card, replayed=False)
    hitl.get_card.return_value = card
    intent = AsyncMock()
    intent.resume_after_tool_approval = AsyncMock()
    document_ingest = AsyncMock()
    document_ingest.execute_after_approval = AsyncMock(return_value={"chunk_count": 2})
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        document_ingest_service=document_ingest,
    )

    body = HITLResolveRequest(action_id="approve", action_token="t" * 32, idempotency_key="idem-doc")
    outcome = await facade.respond(
        "card-1",
        body,
        actor_subject="user-1",
        actor_org_id="org-1",
        is_admin=False,
    )

    assert outcome.resumed is None
    intent.resume_after_tool_approval.assert_not_awaited()
    document_ingest.execute_after_approval.assert_awaited_once_with(task_id="doc-ingest-abc123")


@pytest.mark.asyncio
async def test_respond_mem_save_skips_graph_resume() -> None:
    card = _card(purpose="mcp_tool_approval")
    card = card.model_copy(update={"task_id": "mem-save-abc123"})
    hitl = AsyncMock()
    hitl.resolve.return_value = _resolve_result(card, replayed=False)
    hitl.get_card.return_value = card
    intent = AsyncMock()
    intent.resume_after_tool_approval = AsyncMock()
    memory_save = AsyncMock()
    memory_save.execute_after_approval = AsyncMock(return_value={"entry_key": "pref"})
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_save_service=memory_save,
    )

    body = HITLResolveRequest(action_id="approve", action_token="t" * 32, idempotency_key="idem-mem")
    outcome = await facade.respond(
        "card-1",
        body,
        actor_subject="user-1",
        actor_org_id="org-1",
        is_admin=False,
    )

    assert outcome.resumed is None
    intent.resume_after_tool_approval.assert_not_awaited()
    memory_save.execute_after_approval.assert_awaited_once_with(task_id="mem-save-abc123")


@pytest.mark.asyncio
async def test_respond_mem_forget_skips_graph_resume() -> None:
    card = _card(purpose="mcp_tool_approval")
    card = card.model_copy(update={"task_id": "mem-forget-abc123"})
    hitl = AsyncMock()
    hitl.resolve.return_value = _resolve_result(card, replayed=False)
    hitl.get_card.return_value = card
    intent = AsyncMock()
    intent.resume_after_tool_approval = AsyncMock()
    memory_forget = AsyncMock()
    memory_forget.execute_after_approval = AsyncMock(return_value={"entry_key": "pref"})
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_forget_service=memory_forget,
    )

    body = HITLResolveRequest(action_id="approve", action_token="t" * 32, idempotency_key="idem-mem-forget")
    outcome = await facade.respond(
        "card-1",
        body,
        actor_subject="user-1",
        actor_org_id="org-1",
        is_admin=False,
    )

    assert outcome.resumed is None
    intent.resume_after_tool_approval.assert_not_awaited()
    memory_forget.execute_after_approval.assert_awaited_once_with(task_id="mem-forget-abc123")


@pytest.mark.asyncio
async def test_respond_mem_consolidate_skips_graph_resume() -> None:
    card = _card(purpose="mcp_tool_approval")
    card = card.model_copy(update={"task_id": "mem-consolidate-abc123"})
    hitl = AsyncMock()
    hitl.resolve.return_value = _resolve_result(card, replayed=False)
    hitl.get_card.return_value = card
    intent = AsyncMock()
    intent.resume_after_tool_approval = AsyncMock()
    memory_consolidate = AsyncMock()
    memory_consolidate.execute_after_approval = AsyncMock(return_value={"thread_id": "th-1"})
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_consolidate_service=memory_consolidate,
    )

    body = HITLResolveRequest(action_id="approve", action_token="t" * 32, idempotency_key="idem-mem-consolidate")
    outcome = await facade.respond(
        "card-1",
        body,
        actor_subject="user-1",
        actor_org_id="org-1",
        is_admin=False,
    )

    assert outcome.resumed is None
    intent.resume_after_tool_approval.assert_not_awaited()
    memory_consolidate.execute_after_approval.assert_awaited_once_with(task_id="mem-consolidate-abc123")


@pytest.mark.asyncio
async def test_respond_resumes_mcp_tool_approval() -> None:
    card = _card()
    hitl = AsyncMock()
    hitl.resolve.return_value = _resolve_result(card, replayed=False)
    hitl.get_card.return_value = card
    resumed = _formatter_result()
    intent = AsyncMock()
    intent.resume_after_tool_approval = AsyncMock(return_value=resumed)
    facade = HitlRespondFacade(hitl_service=hitl, intent_service=intent)

    body = HITLResolveRequest(action_id="approve", action_token="t" * 32, idempotency_key="idem-5678")
    outcome = await facade.respond(
        "card-1",
        body,
        actor_subject="user-1",
        actor_org_id="org-1",
        is_admin=False,
    )

    assert outcome.resumed is resumed
    intent.resume_after_tool_approval.assert_awaited_once_with(
        thread_id="th-1",
        task_id="task-1",
        action_id="approve",
        user_id="user-1",
        org_id="org-1",
        is_admin=False,
    )
