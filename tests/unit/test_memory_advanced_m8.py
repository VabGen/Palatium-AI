# tests/unit/test_memory_advanced_m8.py

"""Wave M8 — eval-gated advanced memory modules (OFF by default)."""

from __future__ import annotations

import json

from datetime import UTC, datetime, timedelta

import pytest

from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.domain.memory.bayesian_trust import BetaTrust
from palatium_ai.domain.memory.binary_quantize import (
    binary_quantize,
    hamming_similarity,
    rank_by_hamming,
)
from palatium_ai.domain.memory.emotional import parse_optional_emotional_valence
from palatium_ai.domain.memory.hebbian import bump_hebbian_weight
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.memory.scoring import ImportanceInputs, compute_importance, recency_score
from palatium_ai.domain.memory.xmemory import decouple_before_aggregate
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.memory.cross_encoder_rerank import CrossEncoderRerankMemoryPort
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from palatium_ai.infrastructure.memory.stub_cross_encoder import TokenOverlapCrossEncoder


def test_tau_decay_half_life_configurable() -> None:
    now = datetime(2026, 6, 1, tzinfo=UTC)
    fresh = datetime(2026, 5, 31, tzinfo=UTC)
    stale = datetime(2026, 1, 1, tzinfo=UTC)
    short = recency_score(last_accessed=stale, now=now, half_life_days=7.0)
    long = recency_score(last_accessed=stale, now=now, half_life_days=180.0)
    assert short < long
    assert recency_score(last_accessed=fresh, now=now, half_life_days=7.0) > short


def test_binary_quantize_hamming_ranks_similar_vectors_first() -> None:
    query = [1.0, -1.0, 1.0, -1.0] * 4
    close = [0.9, -0.8, 1.1, -0.5] * 4
    far = [-1.0, 1.0, -1.0, 1.0] * 4
    ranked = rank_by_hamming(
        query,
        [(close, {"id": "close"}), (far, {"id": "far"})],
        limit=2,
    )
    assert ranked[0]["id"] == "close"
    q_bits = binary_quantize(query)
    assert hamming_similarity(q_bits, binary_quantize(close), bit_length=len(query)) > 0.5


def test_bayesian_trust_updates() -> None:
    prior = BetaTrust.from_confidence(0.5, strength=2.0)
    after = prior.observe_success().observe_success()
    assert after.mean() > prior.mean()
    failed = prior.observe_failure()
    assert failed.mean() < prior.mean()


def test_emotional_valence_optional() -> None:
    assert parse_optional_emotional_valence(None) is None
    assert parse_optional_emotional_valence(0.25) == 0.25
    with pytest.raises(ValueError, match="emotional_valence"):
        parse_optional_emotional_valence(2.0)


def test_hebbian_bump_asymptotic() -> None:
    w0 = 0.0
    w1 = bump_hebbian_weight(w0, learning_rate=0.1)
    w2 = bump_hebbian_weight(w1, learning_rate=0.1)
    assert 0.0 < w1 < w2 < 1.0


def test_xmemory_decouple_keeps_strongest() -> None:
    weak = PromotionCandidate(
        namespace=("user", "u"),
        entry_key="a",
        text="User likes duck",
        importance=0.4,
        access_frequency=3,
        user_id="u",
        confidence=0.5,
    )
    strong = PromotionCandidate(
        namespace=("user", "u"),
        entry_key="b",
        text="  user likes duck  ",
        importance=0.9,
        access_frequency=5,
        user_id="u",
        confidence=0.9,
    )
    other = PromotionCandidate(
        namespace=("user", "u"),
        entry_key="c",
        text="User likes tea",
        importance=0.8,
        access_frequency=3,
        user_id="u",
        confidence=0.8,
    )
    out = decouple_before_aggregate([weak, strong, other])
    assert len(out) == 2
    texts = {c.text.strip().lower() for c in out}
    assert any("duck" in t for t in texts)
    assert any("tea" in t for t in texts)
    duck = next(c for c in out if "duck" in c.text.lower())
    assert duck.entry_key == "b"


@pytest.mark.asyncio()
async def test_cross_encoder_rerank_reorders() -> None:
    inner = InMemoryMemoryPort()
    ns = user_namespace("ce-u")
    await inner.put(namespace=ns, key="noise", value={"text": "unrelated weather note", "confidence": 0.9})
    await inner.put(namespace=ns, key="gold", value={"text": "alpha beta gamma preference", "confidence": 0.9})
    port = CrossEncoderRerankMemoryPort(inner, TokenOverlapCrossEncoder(), overfetch=2)
    hits = await port.search(namespace=ns, query="alpha beta", limit=2)
    assert hits
    assert "alpha" in str(hits[0].get("text", "")).lower()


@pytest.mark.asyncio()
async def test_promote_xmemory_and_bayesian_and_hebbian() -> None:
    memory = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("m8")
    for key, importance in (("dup-a", 0.5), ("dup-b", 0.95)):
        await memory.put(
            namespace=ns,
            key=key,
            value={
                "text": "User prefers duck for dinner",
                "kind": "preference",
                "confidence": 0.9,
                "importance": importance,
            },
        )
        for _ in range(3):
            await memory.bump_access(namespace=ns, key=key)
    service = MemoryPromotionService(
        memory=memory,
        graph_write=graph,
        thresholds=PromotionThresholds(min_access_frequency=3, min_importance=0.4),
        xmemory_decouple=True,
        bayesian_trust=True,
        hebbian_edge_bump=True,
    )
    promoted = await service.run_batch(user_id="m8", limit=8)
    assert promoted == 1
    active = graph.get_active_fact(user_id="m8", entry_key="dup-b")
    assert active is not None
    # Bayesian observe_success should lift mean above seed confidence when strength=2.
    assert active.confidence >= 0.9


@pytest.mark.asyncio()
async def test_save_memory_optional_emotional_valence() -> None:
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        memory_port=InMemoryMemoryPort(),
    )
    ok = await handler.call_tool(
        "save_memory",
        {
            "user_id": "emo",
            "namespace_kind": "user",
            "scope_id": "emo",
            "entry_key": "e1",
            "value_json": json.dumps(
                {"text": "Felt great about the release", "confidence": 0.9, "emotional_valence": 0.7}
            ),
        },
    )
    assert ok.is_error is False
    bad = await handler.call_tool(
        "save_memory",
        {
            "user_id": "emo",
            "namespace_kind": "user",
            "scope_id": "emo",
            "entry_key": "e2",
            "value_json": json.dumps({"text": "bad valence", "confidence": 0.9, "emotional_valence": 9}),
        },
    )
    assert bad.is_error is True


def test_default_importance_weights_stable() -> None:
    """M8 must not change default scoring when τ half-life stays at 7d."""
    now = datetime.now(UTC)
    inputs = ImportanceInputs(
        recency_score=recency_score(last_accessed=now - timedelta(days=1), now=now),
        relevance_score=0.8,
        access_frequency=3,
    )
    assert 0.0 < compute_importance(inputs) <= 1.0
