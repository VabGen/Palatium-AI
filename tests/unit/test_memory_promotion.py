# tests/unit/test_memory_promotion.py

"""PromotionPolicy gate + bump-on-recall + batch promote (060)."""

from __future__ import annotations

import asyncio

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
        kind="fact",
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


def test_preference_promotes_without_access_bumps() -> None:
    """Identity prefs are durable on write — Neo4j must not wait for reconsolidation."""
    thresholds = PromotionThresholds(min_access_frequency=3, min_importance=0.7)
    pref = PromotionCandidate(
        namespace=("user", "u1"),
        entry_key="name",
        text="User's name is Gennady",
        kind="preference",
        importance=0.9,
        access_frequency=0,
        user_id="u1",
        confidence=0.95,
    )
    assert PromotionPolicy.required_access_frequency("preference", thresholds=thresholds) == 0
    assert PromotionPolicy.should_promote(pref, thresholds=thresholds) is True
    fact_same = pref.model_copy(update={"kind": "fact"})
    assert PromotionPolicy.should_promote(fact_same, thresholds=thresholds) is False


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
    assert PromotionPolicy.effective_importance(candidate, now=now) == PromotionPolicy.effective_importance(with_tz, now=now)


@pytest.mark.asyncio()
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


@pytest.mark.asyncio()
async def test_promotion_batch_upserts_preference_without_bumps() -> None:
    port = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("alice")
    await port.put(
        namespace=ns,
        key="pref-name",
        value={
            "text": "User's name is Gennady",
            "kind": "preference",
            "confidence": 0.95,
            "importance": 0.9,
        },
    )

    service = MemoryPromotionService(
        memory=port,
        graph_write=graph,
        thresholds=PromotionThresholds(min_access_frequency=3, min_importance=0.7),
    )
    promoted = await service.run_batch(user_id="alice", limit=8)
    assert promoted == 1
    assert len(graph.facts) == 1
    fact = next(iter(graph.facts.values()))
    assert "gennady" in fact.text.lower()
    assert fact.user_id == "alice"
    assert fact.kind == "preference"

    # Idempotent: already promoted → no second upsert mark
    promoted_again = await service.run_batch(user_id="alice", limit=8)
    assert promoted_again == 0
    assert len(graph.facts) == 1


@pytest.mark.asyncio()
async def test_two_promoters_do_not_write_the_same_candidate_twice() -> None:
    """F6 regression: read-then-write promote needs a claim, not just a candidate list.

    Both services see the same candidate (the listing is not a reservation). Without a
    claim each one upserts, and two active ``:MemoryFact`` nodes with one ``node_id``
    appear on the stand. With the claim the loser skips, so one graph write happens.
    """
    port = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("alice")
    await port.put(
        namespace=ns,
        key="pref-name",
        value={"text": "User's name is Gennady", "kind": "preference", "confidence": 0.95, "importance": 0.9},
    )
    first = MemoryPromotionService(memory=port, graph_write=graph)
    second = MemoryPromotionService(memory=port, graph_write=graph)

    promoted = await asyncio.gather(
        first.run_batch(user_id="alice", limit=8),
        second.run_batch(user_id="alice", limit=8),
    )

    assert sum(promoted) == 1
    assert len(graph.facts) == 1


@pytest.mark.asyncio()
async def test_claim_is_exclusive_and_released_after_a_skip() -> None:
    port = InMemoryMemoryPort()
    ns = user_namespace("alice")
    await port.put(namespace=ns, key="k1", value={"text": "fact", "kind": "fact", "confidence": 0.9})

    assert await port.claim_promotion(namespace=ns, key="k1") is True
    assert await port.claim_promotion(namespace=ns, key="k1") is False
    # A held claim also hides the row from the candidate listing.
    assert await port.list_promotion_candidates(user_id="alice", min_access_frequency=0, min_importance=0.0) == []

    assert await port.release_promotion(namespace=ns, key="k1") is True
    assert await port.claim_promotion(namespace=ns, key="k1") is True


@pytest.mark.asyncio()
async def test_expired_claim_lease_is_reclaimable() -> None:
    """A crashed promoter must not park the candidate forever."""
    from datetime import timedelta

    port = InMemoryMemoryPort()
    ns = user_namespace("alice")
    await port.put(namespace=ns, key="k1", value={"text": "fact", "kind": "fact", "confidence": 0.9})
    assert await port.claim_promotion(namespace=ns, key="k1", lease_seconds=1) is True

    # Age the claim past its lease instead of sleeping a second in the test.
    port._meta[(ns, "k1")].promote_claimed_at = datetime.now(UTC) - timedelta(seconds=5)

    assert await port.claim_promotion(namespace=ns, key="k1", lease_seconds=1) is True


@pytest.mark.asyncio()
async def test_rewritten_content_becomes_a_promotion_candidate_again() -> None:
    """F5 regression: promoted_at follows the content, not the row.

    Keeping the stamp after a rewrite is what leaves the graph on the first statement
    forever: the listing filters ``promoted_at IS NULL`` and never sees the new text.
    """
    port = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("alice")
    await port.put(
        namespace=ns, key="db-port", value={"text": "port is 5432", "kind": "preference", "confidence": 0.9, "importance": 0.9}
    )
    service = MemoryPromotionService(memory=port, graph_write=graph)
    assert await service.run_batch(user_id="alice", limit=8) == 1
    assert await service.run_batch(user_id="alice", limit=8) == 0

    await port.put(
        namespace=ns, key="db-port", value={"text": "port is 5433", "kind": "preference", "confidence": 0.9, "importance": 0.9}
    )

    assert await service.run_batch(user_id="alice", limit=8) == 1
    active = graph.get_active_fact(user_id="alice", entry_key="db-port")
    assert active is not None
    assert active.text == "port is 5433"


@pytest.mark.asyncio()
async def test_unchanged_content_keeps_the_promotion_marker() -> None:
    """A retried extract of the same sentence must not re-run promote."""
    port = InMemoryMemoryPort()
    ns = user_namespace("alice")
    value = {"text": "port is 5433", "kind": "preference", "confidence": 0.9, "importance": 0.9}
    await port.put(namespace=ns, key="db-port", value=value)
    assert await port.claim_promotion(namespace=ns, key="db-port") is True
    assert await port.mark_promoted(namespace=ns, key="db-port") is True

    # Only provenance changed (another task id), the promoted payload is identical.
    await port.put(namespace=ns, key="db-port", value={**value, "task_id": "other-task"})

    assert await port.list_promotion_candidates(user_id="alice", min_access_frequency=0, min_importance=0.0) == []
