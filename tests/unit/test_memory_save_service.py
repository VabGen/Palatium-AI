"""MemorySaveService — HITL-gated user-initiated save_memory."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.memory_save_service import MEM_SAVE_TASK_PREFIX, MemorySaveService
from palatium_ai.domain.hitl.cards import HITLCardView, HITLResolveRequest
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import make_platform_mcp_registry


@pytest.fixture
def memory_save_stack() -> tuple[MemorySaveService, InMemoryMemoryPort, HitlService]:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    service = MemorySaveService(hitl_service=hitl, mcp_registry=registry)
    return service, port, hitl


@pytest.mark.asyncio
async def test_memory_save_requires_hitl_before_write(
    memory_save_stack: tuple[MemorySaveService, InMemoryMemoryPort, HitlService],
) -> None:
    service, port, _hitl = memory_save_stack
    card = await service.request_save(
        thread_id="thread-1",
        owner_user_id="user-1",
        org_id="org-1",
        namespace_kind="user",
        scope_id="user-1",
        entry_key="pref-lang",
        text="User prefers Russian responses.",
        memory_type="preference",
    )
    assert isinstance(card, HITLCardView)
    assert card.task_id.startswith(MEM_SAVE_TASK_PREFIX)
    assert card.purpose == "mcp_tool_approval"
    assert "save_memory" in card.title

    # Not written yet
    hits_before = await port.search(namespace=user_namespace("user-1"), query="Russian", limit=4)
    assert hits_before == []

    outcome = await service.execute_after_approval(task_id=card.task_id)
    assert outcome["entry_key"] == "pref-lang"
    hits_after = await port.search(namespace=user_namespace("user-1"), query="Russian", limit=4)
    assert hits_after
    assert "Russian" in str(hits_after[0]["text"])


@pytest.mark.asyncio
async def test_memory_save_reject_discards_pending(
    memory_save_stack: tuple[MemorySaveService, InMemoryMemoryPort, HitlService],
) -> None:
    service, port, _hitl = memory_save_stack
    card = await service.request_save(
        thread_id="thread-2",
        owner_user_id="user-2",
        org_id="org-2",
        namespace_kind="thread",
        scope_id="thread-2",
        entry_key="temp-note",
        text="Temporary note that should not persist.",
    )
    await service.discard_pending(task_id=card.task_id)
    with pytest.raises(ValueError, match="pending memory save missing"):
        await service.execute_after_approval(task_id=card.task_id)
    hits = await port.search(namespace=("chat", "thread", "thread-2"), query="Temporary", limit=4)
    assert hits == []


@pytest.mark.asyncio
async def test_memory_save_rejects_foreign_user_scope(
    memory_save_stack: tuple[MemorySaveService, InMemoryMemoryPort, HitlService],
) -> None:
    service, port, _hitl = memory_save_stack
    with pytest.raises(ValueError, match="authenticated user"):
        await service.request_save(
            thread_id="thread-idor",
            owner_user_id="user-attacker",
            org_id="org-1",
            namespace_kind="user",
            scope_id="user-victim",
            entry_key="stolen",
            text="Should not land in victim namespace.",
        )
    hits = await port.search(namespace=user_namespace("user-victim"), query="Should not", limit=4)
    assert hits == []


@pytest.mark.asyncio
async def test_memory_save_classifies_pii_despite_client_false(
    memory_save_stack: tuple[MemorySaveService, InMemoryMemoryPort, HitlService],
) -> None:
    service, _port, _hitl = memory_save_stack
    card = await service.request_save(
        thread_id="thread-pii",
        owner_user_id="user-pii",
        org_id="org-1",
        namespace_kind="user",
        scope_id="user-pii",
        entry_key="contact",
        text="Reach me at alice@example.com please.",
        contains_pii=False,
    )
    pending = await service._load_pending(card.task_id)  # noqa: SLF001
    assert pending is not None
    assert '"contains_pii": true' in pending.value_json


@pytest.mark.asyncio
async def test_hitl_respond_facade_runs_memory_save_on_approve(
    memory_save_stack: tuple[MemorySaveService, InMemoryMemoryPort, HitlService],
) -> None:
    from unittest.mock import AsyncMock

    from palatium_ai.application.services.hitl_respond_facade import HitlRespondFacade

    service, port, hitl = memory_save_stack
    card = await service.request_save(
        thread_id="thread-3",
        owner_user_id="user-3",
        org_id="org-3",
        namespace_kind="user",
        scope_id="user-3",
        entry_key="pref-tables",
        text="User prefers tables for agendas.",
        memory_type="preference",
    )
    approve = next(opt for opt in card.options if opt.action_id == "approve")
    intent = AsyncMock()
    facade = HitlRespondFacade(
        hitl_service=hitl,
        intent_service=intent,
        memory_save_service=service,
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
    assert hits
    intent.resume_after_tool_approval.assert_not_called()
