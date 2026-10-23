# tests/eval/test_m9_eval_metrics.py

"""M9 step 1: the three metrics that M8 flags had no consumer for.

Each test runs *real* code (promote batch, rerank decorator, graph write port) and records
a baseline number. None of the M8 flags is enabled here — that is deliberate: the plan's
step 2 is "baseline while every flag is false", and a baseline taken with the candidate
flag on proves nothing.

Limits are stated where they exist: the embedding stand-in is deterministic (no provider),
and the reinforcement test measures the *absence* of a ranking consumer rather than a
model effect.
"""

from __future__ import annotations

import re

import pytest

from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.domain.memory.eval_metrics import (
    context_precision_at_k,
    recall_at_k,
    reinforcement_lift,
    supersede_precision,
    supersede_recall,
)
from palatium_ai.domain.memory.namespaces import thread_namespace, user_namespace
from palatium_ai.domain.memory.promotion import PromotionThresholds
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.memory.embedding_rerank import EmbeddingRerankMemoryPort
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


@pytest.mark.asyncio()
async def test_eval_supersede_precision_and_recall_on_a_contradiction_corpus() -> None:
    """Corpus: 4 promote candidates, 2 of which contradict an active L4 fact.

    Expected outcome: the non-PII contradiction is superseded, the restated fact is only
    refreshed, a brand-new key is created — and the **PII** contradiction is withheld.
    That last one is the measured F3 debt: it shows up as recall 0.5, not as an error.
    """
    memory = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("m9-supersede")

    seeded = (
        ("python", "User uses Python", False),
        ("office", "User's office is in Berlin", False),
        ("pii-ssn", "SSN is 123-45-6789", True),
    )
    for key, text, pii in seeded:
        await graph.upsert_fact(GraphFactUpsert(user_id="m9-supersede", entry_key=key, text=text, kind="fact", contains_pii=pii))

    candidates = (
        ("python", "User uses Go", False),
        ("office", "User's office is in Berlin", False),
        ("pii-ssn", "SSN is 999-99-9999", True),
        ("theme", "User prefers dark mode", False),
    )
    for key, text, pii in candidates:
        await memory.put(
            namespace=ns,
            key=key,
            value={"text": text, "kind": "fact", "confidence": 0.9, "importance": 0.9, "contains_pii": pii},
        )
        for _ in range(3):
            await memory.bump_access(namespace=ns, key=key)

    service = MemoryPromotionService(
        memory=memory,
        graph_write=graph,
        thresholds=PromotionThresholds(min_access_frequency=3, min_importance=0.7),
    )
    assert await service.run_batch(user_id="m9-supersede", limit=8) == 3

    superseded = [
        key
        for key in ("python", "office", "pii-ssn", "theme")
        if (active := graph.get_active_fact(user_id="m9-supersede", entry_key=key)) is not None and active.version > 1
    ]
    expected = frozenset({"python", "pii-ssn"})

    assert superseded == ["python"]
    assert supersede_precision(superseded_keys=superseded, expected_keys=expected) == pytest.approx(1.0)
    # 0.5 == "one of two contradictions resolved": the PII flip waits for a human (F3).
    assert supersede_recall(superseded_keys=superseded, expected_keys=expected) == pytest.approx(0.5)

    # What the batch must NOT have done: overwrite the restated fact, create a version of
    # the blocked PII fact, or bump the brand-new key to v2.
    assert graph.get_active_fact(user_id="m9-supersede", entry_key="office").version == 1  # type: ignore[union-attr]
    assert "123-45-6789" in graph.get_active_fact(user_id="m9-supersede", entry_key="pii-ssn").text  # type: ignore[union-attr]
    assert graph.get_active_fact(user_id="m9-supersede", entry_key="theme").version == 1  # type: ignore[union-attr]


class _TopicEmbeddings:
    """Deterministic semantic stand-in: one axis per topic, no provider call.

    This is a *mechanic* probe of the rerank decorator, not a measurement of a real
    embedding model — a real one is only reachable in the live eval path.
    """

    _TOPICS: tuple[frozenset[str], ...] = (
        frozenset({"tables", "table", "tabular", "таблиц"}),
        frozenset({"tennis", "racket"}),
    )

    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        _ = model
        return [self._vector(text) for text in texts]

    @classmethod
    def _vector(cls, text: str) -> list[float]:
        tokens = set(re.findall(r"\w+", text.lower()))
        return [1.0 if tokens & topic else 0.0 for topic in cls._TOPICS]


@pytest.mark.asyncio()
async def test_eval_context_precision_at_k_improves_after_rerank() -> None:
    """A token-stuffed distractor wins the lexical pass; rerank must not keep it in top-2."""
    inner = InMemoryMemoryPort()
    ns = thread_namespace("m9-rerank")
    corpus = {
        "b": ("User prefers tables for meeting agendas", 0.9),
        "c": ("Meeting agendas should be tables, not prose", 0.8),
        # Shares three query tokens while carrying no relevant content — the baseline
        # ranks it above "c" purely on overlap.
        "d": ("Meeting agendas for the meeting: agendas list for all attendees", 0.95),
        "e": ("Unrelated invoice template", 0.7),
    }
    for key, (text, confidence) in corpus.items():
        await inner.put(namespace=ns, key=key, value={"text": text, "kind": "fact", "confidence": confidence})

    relevant = frozenset({"b", "c"})
    query = "tables for meeting agendas"
    k = 2

    baseline_hits = await inner.search(namespace=ns, query=query, limit=k)
    baseline_keys = [str(hit.get("_entry_key", "")) for hit in baseline_hits]

    reranked = EmbeddingRerankMemoryPort(inner, _TopicEmbeddings())  # type: ignore[arg-type]
    reranked_hits = await reranked.search(namespace=ns, query=query, limit=k)
    reranked_keys = [str(hit.get("_entry_key", "")) for hit in reranked_hits]

    baseline_precision = context_precision_at_k(retrieved_keys=baseline_keys, relevant_keys=relevant, k=k)
    rerank_precision = context_precision_at_k(retrieved_keys=reranked_keys, relevant_keys=relevant, k=k)

    assert baseline_keys == ["b", "d"]
    assert baseline_precision == pytest.approx(0.5)
    assert reranked_keys == ["b", "c"]
    assert rerank_precision == pytest.approx(1.0)
    # The flag's acceptance bar (M9 §5.3): precision up, Recall@k not down.
    assert rerank_precision > baseline_precision
    assert recall_at_k(retrieved_keys=reranked_keys, relevant_keys=relevant, k=k) >= recall_at_k(
        retrieved_keys=baseline_keys, relevant_keys=relevant, k=k
    )


@pytest.mark.asyncio()
async def test_eval_reinforcement_lift_is_zero_because_no_ranker_reads_the_weight() -> None:
    """The Hebbian weight grows, but nothing consumes it — lift is exactly 0 by design.

    This is the precondition M9 §6 step 6 names: a Hebbian flag would change stored state
    and nothing else, which is why the knob was removed (§9.2) while the port capability
    stays. When a ranker starts reading the weight, this 0.0 must be revisited on purpose
    (baseline update), not silently drift.
    """
    graph = InMemoryGraphWritePort()
    keys = [f"f{index}" for index in range(8)]
    for key in keys:
        await graph.upsert_fact(
            GraphFactUpsert(user_id="m9-lift", entry_key=key, text=f"fact {key}", kind="fact", importance=0.5, confidence=0.5)
        )

    reinforced_keys = {"f0", "f2", "f4", "f6"}
    for key in keys:
        if key in reinforced_keys:
            await graph.bump_hebbian_on_entry(user_id="m9-lift", entry_key=key)

    # Weight exists and is asymptotic (0.1 then 0.19) — the bump is not a no-op.
    assert await graph.bump_hebbian_on_entry(user_id="m9-lift", entry_key="f0") == pytest.approx(0.19)

    selected_keys = {record.entry_key for record in await graph.list_active_facts(user_id="m9-lift", limit=4)}
    lift = reinforcement_lift(
        reinforced=[key in reinforced_keys for key in keys],
        selected=[key in selected_keys for key in keys],
    )

    assert selected_keys == {"f0", "f1", "f2", "f3"}
    assert lift == pytest.approx(0.0)
