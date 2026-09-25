# tests/unit/test_memory_promotion.py

"""PromotionPolicy gate + bump-on-recall + batch promote (060)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.domain.memory.namespaces import thread_namespace, user_namespace
from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.policies.promotion import PromotionPolicy
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from palatium_ai.infrastructure.memory.postgres_memory_port import decode_namespace, encode_namespace


def test_decode_namespace_roundtrip() -> None:
    ns = ("chat", "thread", "t1")
    assert decode_namespace(encode_namespace(ns)) == ns


def test_promotion_policy_requires_access_and_importance() -> None:
    thresholds = PromotionThresholds(min_access_frequency=3, min_importance=0.7)
    low_access = PromotionCandidate(
        namespace=("user", "u1"),
        entry_key="k1",
        text="likes duck for dinner",
        importance=0.9,
        access_frequency=2,
        user_id="u1",
        confidence=0.9,
    )
    assert PromotionPolicy.should_promote(low_access, thresholds=thresholds) is False

    ready = low_access.model_copy(update={"access_frequency": 3})
    assert PromotionPolicy.should_promote(ready, thresholds=thresholds) is True

    already = ready.model_copy(update={"promoted_at": datetime.now(UTC)})
    assert PromotionPolicy.should_promote(already, thresholds=thresholds) is False


def test_promotion_policy_rejects_blank_text() -> None:
    """A row whose text is only whitespace is not promotable (nothing to store)."""
    thresholds = PromotionThresholds(min_access_frequency=1, min_importance=0.0)
    blank = PromotionCandidate(
        namespace=("user", "u1"),
        entry_key="blank",
        text="   ",
        importance=0.9,
        access_frequency=5,
        user_id="u1",
        confidence=0.9,
    )
    assert PromotionPolicy.should_promote(blank, thresholds=thresholds) is False


def test_effective_importance_treats_naive_timestamp_as_utc() -> None:
    """Legacy rows may carry naive timestamps; recency must still be computed (060/010)."""
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    candidate = PromotionCandidate(
        namespace=("user", "u1"),
        entry_key="naive",
        text="likes duck for dinner",
        importance=0.0,
        access_frequency=3,
        user_id="u1",
        confidence=0.9,
        last_accessed=datetime(2026, 1, 1, 11, 0),  # naive on purpose
    )

    with_tz = candidate.model_copy(update={"last_accessed": datetime(2026, 1, 1, 11, 0, tzinfo=UTC)})
    assert PromotionPolicy.effective_importance(candidate, now=now) == PromotionPolicy.effective_importance(
        with_tz, now=now
    )


@pytest.mark.asyncio
async def test_recall_bumps_access_frequency() -> None:
    port = InMemoryMemoryPort()
    ns = thread_namespace("promo-t1")
    await port.put(
        namespace=ns,
        key="duck",
        value={"text": "User wanted duck for dinner", "kind": "fact", "confidence": 0.95, "importance": 0.9},
    )
    assert await port.bump_access(namespace=ns, key="missing") == 0

    bundle = await recall_for_thread(port, thread_id="promo-t1", query="dinner duck", limit=4)
    assert bundle.hits
    assert await port.bump_access(namespace=ns, key="duck") == 2  # recall bumped once → next is 2


@pytest.mark.asyncio
async def test_promotion_batch_upserts_graph_and_marks() -> None:
    port = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("alice")
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
        assert await port.bump_access(namespace=ns, key="pref-duck") >= 1

    service = MemoryPromotionService(
        memory=port,
        graph_write=graph,
        thresholds=PromotionThresholds(min_access_frequency=3, min_importance=0.7),
    )
    promoted = await service.run_batch(user_id="alice", limit=8)
    assert promoted == 1
    assert len(graph.facts) == 1
    fact = next(iter(graph.facts.values()))
    assert "duck" in fact.text.lower()
    assert fact.user_id == "alice"

    # Idempotent: already promoted → no second upsert mark
    promoted_again = await service.run_batch(user_id="alice", limit=8)
    assert promoted_again == 0
    assert len(graph.facts) == 1
