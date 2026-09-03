"""MemoryForgetService — HITL-gated user-initiated forget_memory."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade
from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.memory_forget_service import (
    MEM_FORGET_TASK_PREFIX,
    MemoryForgetService,
)
from palatium_ai.domain.hitl.cards import HITLCardView, HITLResolveRequest
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import make_platform_mcp_registry


@pytest.fixture
def memory_forget_stack() -> tuple[MemoryForgetService, InMemoryMemoryPort, HitlService]:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    service = MemoryForgetService(hitl_service=hitl, mcp_registry=registry)
    return service, port, hitl


@pytest.mark.asyncio
async def test_memory_forget_requires_hitl_before_delete(
    memory_forget_stack: tuple[MemoryForgetService, InMemoryMemoryPort, HitlService],
) -> None:
    service, port, _hitl = memory_forget_stack
    await port.put(
        namespace=user_namespace("user-1"),
        key="pref-lang",
        value={"text": "User prefers Russian responses.", "user_id": "user-1"},
    )
    card = await service.request_forget(
        thread_id="thread-1",
        owner_user_id="user-1",
        org_id="org-1",
        namespace_kind="user",
        scope_id="user-1",
        entry_key="pref-lang",
    )
    assert isinstance(card, HITLCardView)
    assert card.task_id.startswith(MEM_FORGET_TASK_PREFIX)
    assert card.purpose == "mcp_tool_approval"
    assert "forget_memory" in card.title

    hits_before = await port.search(namespace=user_namespace("user-1"), query="Russian", limit=4)
    assert hits_before

    outcome = await service.execute_after_approval(task_id=card.task_id)
    assert outcome["entry_key"] == "pref-lang"
    hits_after = await port.search(namespace=user_namespace("user-1"), query="Russian", limit=4)
    assert hits_after == []


@pytest.mark.asyncio
async def test_memory_forget_reject_discards_pending(
    memory_forget_stack: tuple[MemoryForgetService, InMemoryMemoryPort, HitlService],
) -> None:
    service, port, _hitl = memory_forget_stack
    await port.put(
        namespace=user_namespace("user-2"),
        key="keep-me",
        value={"text": "Should survive reject.", "user_id": "user-2"},
    )
    card = await service.request_forget(
        thread_id="thread-2",
        owner_user_id="user-2",
        org_id="org-2",
        namespace_kind="user",
        scope_id="user-2",
        entry_key="keep-me",
    )
    await service.discard_pending(task_id=card.task_id)
    with pytest.raises(ValueError, match="pending memory forget missing"):
        await service.execute_after_approval(task_id=card.task_id)
    hits = await port.search(namespace=user_namespace("user-2"), query="survive", limit=4)
    assert hits


@pytest.mark.asyncio
async def test_hitl_respond_facade_runs_memory_forget_on_approve(
    memory_forget_stack: tuple[MemoryForgetService, InMemoryMemoryPort, HitlService],
) -> None:
    service, port, hitl = memory_forget_stack
    await port.put(
        namespace=user_namespace("user-3"),
        key="pref-tables",
        value={"text": "User prefers tables for agendas.", "user_id": "user-3"},
    )
    card = await service.request_forget(
        thread_id="thread-3",
        owner_user_id="user-3",
        org_id="org-3",
        namespace_kind="user",
        scope_id="user-3",
        entry_key="pref-tables",
    )
    approve = next(opt for opt in card.options if opt.action_id == "approve")
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_forget_service=service,
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
    hits = await port.search(namespace=user_namespace("user-3"), query="tables", limit=4)
    assert hits == []


@pytest.mark.asyncio
async def test_memory_forget_rejects_foreign_user_scope(
    memory_forget_stack: tuple[MemoryForgetService, InMemoryMemoryPort, HitlService],
) -> None:
    service, port, _hitl = memory_forget_stack
    await port.put(
        namespace=user_namespace("user-victim"),
        key="keep",
        value={"text": "Victim preference.", "user_id": "user-victim"},
    )
    with pytest.raises(ValueError, match="authenticated user"):
        await service.request_forget(
            thread_id="thread-idor",
            owner_user_id="user-attacker",
            org_id="org-1",
            namespace_kind="user",
            scope_id="user-victim",
            entry_key="keep",
        )
    hits = await port.search(namespace=user_namespace("user-victim"), query="Victim", limit=4)
    assert hits
