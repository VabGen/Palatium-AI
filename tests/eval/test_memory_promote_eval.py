# tests/eval/test_memory_promote_eval.py

"""Offline evals for medium → long-term promote (060).

Gates from ANALYZE: bump on recall, policy reject low importance,
high-freq + high-importance → graph node, dual-store coexistence.
"""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.policies.promotion import PromotionPolicy
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


@pytest.mark.asyncio
async def test_eval_recall_increments_access_frequency() -> None:
    """access_frequency increments when a durable hit enters the recall bundle."""
    port = InMemoryMemoryPort()
    ns = user_namespace("eval-promote-user")
    await port.put(
        namespace=ns,
        key="duck",
        value={
            "text": "User wanted duck for dinner",
            "kind": "preference",
            "confidence": 0.95,
            "importance": 0.9,
        },
    )
    bundle = await recall_for_thread(
        port,
        thread_id="eval-promote-thread",
        user_id="eval-promote-user",
        query="dinner duck",
        min_confidence=0.7,
    )
    assert bundle.hits
    count = await port.bump_access(namespace=ns, key="duck")
    assert count == 2  # recall bumped once → next bump is 2


def test_eval_promote_gate_rejects_low_importance() -> None:
    thresholds = PromotionThresholds(min_access_frequency=3, min_importance=0.7)
    candidate = PromotionCandidate(
        namespace=("user", "u"),
        entry_key="weak",
        text="maybe likes teal accents",
        importance=0.4,
        access_frequency=10,
        user_id="u",
        confidence=0.4,
    )
    assert PromotionPolicy.should_promote(candidate, thresholds=thresholds) is False


@pytest.mark.asyncio
async def test_eval_high_freq_promotes_to_graph_node() -> None:
    """Medium entry with freq+importance thresholds → graph upsert + mark."""
    port = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("eval-promote-alice")
    await port.put(
        namespace=ns,
        key="pref-duck",
        value={
            "text": "User prefers duck for dinner",
            "kind": "preference",
            "confidence": 0.95,
            "importance": 0.9,
        },
    )
    for _ in range(3):
        await port.bump_access(namespace=ns, key="pref-duck")

    service = MemoryPromotionService(
        memory=port,
        graph_write=graph,
        thresholds=PromotionThresholds(min_access_frequency=3, min_importance=0.7),
    )
    promoted = await service.run_batch(user_id="eval-promote-alice", limit=8)
    assert promoted == 1
    assert len(graph.facts) == 1
    fact = next(iter(graph.facts.values()))
    assert "duck" in fact.text.lower()
    assert fact.user_id == "eval-promote-alice"

    # Dual-store: medium row still present after promote mark
    medium = await port.get(namespace=ns, key="pref-duck")
    assert medium is not None
    assert "duck" in str(medium.get("text", "")).lower()
    # Idempotent — no second graph write
    assert await service.run_batch(user_id="eval-promote-alice", limit=8) == 0
    assert len(graph.facts) == 1
