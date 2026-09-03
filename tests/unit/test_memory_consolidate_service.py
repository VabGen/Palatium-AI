"""MemoryConsolidateService — HITL-gated user-initiated consolidate_memory."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.memory_consolidate_service import (
    MEM_CONSOLIDATE_TASK_PREFIX,
    MemoryConsolidateService,
)
from palatium_ai.domain.hitl.cards import HITLCardView, HITLResolveRequest
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from tests.conftest import make_platform_mcp_registry


class _FakeConsolidation:
    def __init__(self) -> None:
        self.jobs: list[dict[str, object]] = []

    def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> bool:
        self.jobs.append(
            {
                "thread_id": thread_id,
                "task_id": task_id,
                "user_id": user_id,
                "org_id": org_id,
            }
        )
        return True


@pytest.fixture
def memory_consolidate_stack() -> tuple[MemoryConsolidateService, _FakeConsolidation, HitlService]:
    consolidation = _FakeConsolidation()
    registry = make_platform_mcp_registry(consolidation=consolidation)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    service = MemoryConsolidateService(hitl_service=hitl, mcp_registry=registry)
    return service, consolidation, hitl


@pytest.mark.asyncio
async def test_memory_consolidate_requires_hitl_before_enqueue(
    memory_consolidate_stack: tuple[MemoryConsolidateService, _FakeConsolidation, HitlService],
) -> None:
    service, consolidation, _hitl = memory_consolidate_stack
    card = await service.request_consolidate(
        thread_id="thread-1",
        owner_user_id="user-1",
        org_id="org-1",
        consolidate_task_id="job-explicit-1",
    )
    assert isinstance(card, HITLCardView)
    assert card.task_id.startswith(MEM_CONSOLIDATE_TASK_PREFIX)
    assert "consolidate_memory" in card.title
    assert consolidation.jobs == []

    outcome = await service.execute_after_approval(task_id=card.task_id)
    assert outcome["thread_id"] == "thread-1"
    assert len(consolidation.jobs) == 1
    assert consolidation.jobs[0]["task_id"] == "job-explicit-1"
    assert consolidation.jobs[0]["user_id"] == "user-1"
    assert consolidation.jobs[0]["org_id"] == "org-1"


@pytest.mark.asyncio
async def test_memory_consolidate_reject_discards_pending(
    memory_consolidate_stack: tuple[MemoryConsolidateService, _FakeConsolidation, HitlService],
) -> None:
    service, consolidation, _hitl = memory_consolidate_stack
    card = await service.request_consolidate(
        thread_id="thread-2",
        owner_user_id="user-2",
        org_id="org-2",
    )
    await service.discard_pending(task_id=card.task_id)
    with pytest.raises(ValueError, match="pending memory consolidate missing"):
        await service.execute_after_approval(task_id=card.task_id)
    assert consolidation.jobs == []


@pytest.mark.asyncio
async def test_hitl_respond_facade_runs_memory_consolidate_on_approve(
    memory_consolidate_stack: tuple[MemoryConsolidateService, _FakeConsolidation, HitlService],
) -> None:
    service, consolidation, hitl = memory_consolidate_stack
    card = await service.request_consolidate(
        thread_id="thread-3",
        owner_user_id="user-3",
        org_id="org-3",
    )
    approve = next(opt for opt in card.options if opt.action_id == "approve")
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_consolidate_service=service,
    )
    outcome = await facade.respond(
        card.card_id,
        HITLResolveRequest(
            action_id="approve",
            action_token=approve.action_token,
            idempotency_key=f"idem-{card.card_id}",
        ),
        actor_subject="user-3",
        actor_org_id="org-3",
        is_admin=False,
    )
    assert outcome.resolve.card.status == "resolved"
    assert len(consolidation.jobs) == 1
    intent.resume_after_tool_approval.assert_not_called()
