# tests/unit/test_w11_memory_scope_curation.py

"""W11 Memory Scope & Curation DoD."""

from __future__ import annotations

import asyncio
import json

import pytest

from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.memory_clear_service import MEM_CLEAR_TASK_PREFIX, MemoryClearService
from palatium_ai.application.services.memory_op_worker import MemoryOpWorker
from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.application.services.memory_save_service import MemorySaveService
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.memory.types import MEMORY_TRUST_KEY
from palatium_ai.domain.policies import ExtractAdmissionPolicy, MemoryRecallPolicy
from palatium_ai.domain.policies.promotion import PromotionPolicy
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from palatium_ai.infrastructure.memory.memory_op_queue import InMemoryMemoryOpQueue
from tests.conftest import make_platform_mcp_registry


def test_w11_use_memory_false_blocks_recall() -> None:
    decision = MemoryRecallPolicy.decide(
        task_kind="knowledge_request",
        requires_mcp=False,
        use_memory=False,
    )
    assert decision.allowed is False
    assert decision.reason == "use_memory_disabled"


def test_w11_memory_default_behavior() -> None:
    decision = MemoryRecallPolicy.decide(task_kind="knowledge_request", requires_mcp=False)
    assert decision.allowed is True
    assert decision.reason != "use_memory_disabled"


def test_w11_use_memory_false_blocks_extract() -> None:
    decision = ExtractAdmissionPolicy.decide(
        task_kind="knowledge_request",
        strategy="retrieve_then_reason",
        use_memory=False,
    )
    assert decision.admit is False
    assert decision.reason == "use_memory_disabled"


def test_w11_slow_path_promotion_policy_untouched() -> None:
    """Slow-path access bar for facts still applies (W11 must not weaken cron gates)."""
    inferred = PromotionCandidate(
        namespace=user_namespace("u1"),
        entry_key="fact-1",
        text="Inferred fact",
        kind="fact",
        importance=0.99,
        access_frequency=0,
        user_id="u1",
        confidence=0.99,
        trust="inferred",
    )
    assert PromotionPolicy.should_promote(inferred, thresholds=PromotionThresholds()) is False
    verified_pref = inferred.model_copy(update={"kind": "preference", "trust": "verified", "importance": 0.9, "confidence": 1.0})
    assert PromotionPolicy.should_promote(verified_pref, thresholds=PromotionThresholds()) is True


@pytest.mark.asyncio()
async def test_w11_clear_endpoint_hitl_then_purge() -> None:
    port = InMemoryMemoryPort()
    await port.put(
        namespace=user_namespace("user-clear"),
        key="pref",
        value={"text": "likes tea", "user_id": "user-clear", "kind": "preference", "confidence": 1.0},
    )
    ops = InMemoryMemoryOpQueue()
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    service = MemoryClearService(
        hitl_service=hitl,
        memory_port=port,
        memory_op_queue=ops,
    )
    card = await service.request_clear(
        thread_id="thread-clear",
        owner_user_id="user-clear",
        org_id="org-clear",
    )
    assert card.task_id.startswith(MEM_CLEAR_TASK_PREFIX)
    listed = await port.list_entries(namespace=user_namespace("user-clear"), limit=8)
    assert listed  # not purged until approve

    result = await service.execute_after_approval(task_id=card.task_id)
    assert int(result["deleted"]) >= 1
    assert await port.list_entries(namespace=user_namespace("user-clear"), limit=8) == []
    assert "clear_user_graph" in ops.pending_kinds()


@pytest.mark.asyncio()
async def test_w11_fast_promote_only_for_verified() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    ops = InMemoryMemoryOpQueue()
    service = MemorySaveService(
        hitl_service=hitl,
        mcp_registry=registry,
        memory_op_queue=ops,
        promote_fast_min_score=0.85,
    )
    card = await service.request_save(
        thread_id="t-fast",
        owner_user_id="u-fast",
        org_id="org-fast",
        namespace_kind="user",
        scope_id="u-fast",
        entry_key="pref-color",
        text="Favorite color is blue",
        memory_type="preference",
    )
    outcome = await service.execute_after_approval(task_id=card.task_id)
    assert outcome["fast_promote_enqueued"] is True
    assert "promote_entry" in ops.pending_kinds()

    # Inferred high-confidence must never enqueue via save path (save always stamps verified).
    # Simulate extract-style enqueue refusal: worker promote_verified_fast skips inferred.
    promotion = MemoryPromotionService(
        memory=port,
        graph_write=InMemoryGraphWritePort(),
        thresholds=PromotionThresholds(),
    )
    inferred = PromotionCandidate(
        namespace=user_namespace("u-fast"),
        entry_key="extract-fact",
        text="Poisoned inferred",
        kind="fact",
        importance=0.99,
        access_frequency=99,
        user_id="u-fast",
        confidence=0.99,
        trust="inferred",
    )
    assert await promotion.promote_verified_fast(inferred, min_score=0.85) == "skipped"


@pytest.mark.asyncio()
async def test_w11_durable_queue_used() -> None:
    """Producer is MemoryOpQueue — no BackgroundTasks import on the save path."""
    import inspect

    from palatium_ai.application.services import memory_save_service as mod

    source = inspect.getsource(mod)
    assert "BackgroundTasks" not in source
    assert "memory_op_queue" in source


@pytest.mark.asyncio()
async def test_w11_hot_path_no_neo4j_wait() -> None:
    """process-path promote enqueue returns without awaiting graph upsert."""
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    ops = InMemoryMemoryOpQueue()
    slow_graph = InMemoryGraphWritePort()
    original_upsert = slow_graph.upsert_fact

    async def _slow_upsert(command):  # type: ignore[no-untyped-def]
        await asyncio.sleep(0.3)
        return await original_upsert(command)

    slow_graph.upsert_fact = _slow_upsert  # type: ignore[method-assign]
    service = MemorySaveService(
        hitl_service=hitl,
        mcp_registry=registry,
        memory_op_queue=ops,
        promote_fast_min_score=0.85,
    )
    card = await service.request_save(
        thread_id="t-hot",
        owner_user_id="u-hot",
        org_id="org-hot",
        namespace_kind="user",
        scope_id="u-hot",
        entry_key="pref-hot",
        text="Hot path preference",
        memory_type="preference",
    )
    started = asyncio.get_running_loop().time()
    await service.execute_after_approval(task_id=card.task_id)
    elapsed = asyncio.get_running_loop().time() - started
    assert elapsed < 0.25  # did not await the slow upsert
    assert "promote_entry" in ops.pending_kinds()

    worker = MemoryOpWorker(
        queue=ops,
        memory_port=port,
        graph_write=slow_graph,
        promotion=MemoryPromotionService(memory=port, graph_write=slow_graph),
        promote_fast_min_score=0.85,
        poll_seconds=0.05,
    )
    record = await ops.claim()
    assert record is not None
    await worker._run_claimed(record)  # unit drains one claimed op
    facts = await slow_graph.list_active_facts(user_id="u-hot", limit=8)
    assert any(f.entry_key == "pref-hot" for f in facts)


@pytest.mark.asyncio()
async def test_w11_clear_graph_worker_expires_facts() -> None:
    port = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    from palatium_ai.domain.graph.write_port import GraphFactUpsert

    await graph.upsert_fact(
        GraphFactUpsert(
            user_id="u-g",
            entry_key="k1",
            text="to expire",
            kind="preference",
            importance=1.0,
            confidence=1.0,
            source_namespace=user_namespace("u-g"),
        )
    )
    ops = InMemoryMemoryOpQueue()
    await ops.enqueue(kind="clear_user_graph", user_id="u-g", reason="user_clear")
    worker = MemoryOpWorker(
        queue=ops,
        memory_port=port,
        graph_write=graph,
        promotion=MemoryPromotionService(memory=port, graph_write=graph),
    )
    record = await ops.claim()
    assert record is not None
    await worker._run_claimed(record)
    assert await graph.list_active_facts(user_id="u-g", limit=8) == []


@pytest.mark.asyncio()
async def test_w11_save_below_score_does_not_enqueue() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    ops = InMemoryMemoryOpQueue()
    service = MemorySaveService(
        hitl_service=hitl,
        mcp_registry=registry,
        memory_op_queue=ops,
        promote_fast_min_score=0.85,
    )
    # Patch pending value after request by executing with lowered score via direct helper.
    card = await service.request_save(
        thread_id="t-low",
        owner_user_id="u-low",
        org_id="org-low",
        namespace_kind="user",
        scope_id="u-low",
        entry_key="low-score",
        text="Low score note",
        memory_type="fact",
    )
    payload = await service._load_pending(card.task_id)
    assert payload is not None
    value = json.loads(payload.value_json)
    value["importance"] = 0.5
    value["confidence"] = 0.5
    assert value[MEMORY_TRUST_KEY] == "verified"
    from palatium_ai.domain.memory.save_payload import MemorySavePayload

    lowered = MemorySavePayload(
        task_id=payload.task_id,
        thread_id=payload.thread_id,
        user_id=payload.user_id,
        namespace_kind=payload.namespace_kind,
        scope_id=payload.scope_id,
        entry_key=payload.entry_key,
        value_json=json.dumps(value),
        memory_type=payload.memory_type,
        org_id=payload.org_id,
    )
    await service._store_pending(lowered)
    outcome = await service.execute_after_approval(task_id=card.task_id)
    assert outcome["fast_promote_enqueued"] is False
    assert ops.pending_kinds() == []
