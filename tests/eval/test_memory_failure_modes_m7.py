# tests/eval/test_memory_failure_modes_m7.py

"""Wave M7 / G1 — five memory failure modes as offline gates."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.domain.memory.eval_metrics import (
    context_precision_at_k,
    faithfulness_grounded,
    mean_recall_at_k,
    recall_at_k,
)
from palatium_ai.domain.memory.namespaces import thread_namespace, user_namespace
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.memory.extract_job_queue import InMemoryExtractJobQueue
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


@pytest.mark.asyncio()
async def test_g1_knowledge_loss_forget_expires_graph() -> None:
    """Forgetting medium must not leave a live long-term fact (060 / M5)."""
    memory = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        memory_port=memory,
        graph_write=graph,
    )
    await handler.call_tool(
        "save_memory",
        {
            "user_id": "g1-kl",
            "namespace_kind": "user",
            "scope_id": "g1-kl",
            "entry_key": "fact-1",
            "value_json": json.dumps({"text": "Must not orphan in graph", "confidence": 0.9}),
        },
    )
    await graph.upsert_fact(
        GraphFactUpsert(user_id="g1-kl", entry_key="fact-1", text="Must not orphan in graph")
    )
    forget = await handler.call_tool(
        "forget_memory",
        {
            "user_id": "g1-kl",
            "namespace_kind": "user",
            "scope_id": "g1-kl",
            "entry_key": "fact-1",
        },
    )
    payload = json.loads(forget.content[0]["text"])
    assert payload["forgotten"] is True
    assert payload["graph_expired"] is True
    assert graph.get_active_fact(user_id="g1-kl", entry_key="fact-1") is None


@pytest.mark.asyncio()
async def test_g1_context_degradation_budget_clips() -> None:
    """Unbounded recall must not dump past char budget (065 / G8)."""
    port = InMemoryMemoryPort()
    ns = thread_namespace("g1-budget")
    for idx in range(8):
        await port.put(
            namespace=ns,
            key=f"k{idx}",
            value={
                "text": f"pref-{idx}-" + ("x" * 200),
                "kind": "preference",
                "confidence": 0.95,
                "_score": 10 - idx,
            },
        )
    bundle = await recall_for_thread(
        port,
        thread_id="g1-budget",
        query="pref",
        limit=6,
        max_chars=280,
        min_confidence=0.7,
    )
    assert len(bundle.as_prompt_block()) <= 280


@pytest.mark.asyncio()
async def test_g1_silent_memory_death_low_confidence_empty_not_exception() -> None:
    """Silent Memory Death probe: low-quality memory yields empty hints, not crash."""
    port = InMemoryMemoryPort()
    await port.put(
        namespace=thread_namespace("g1-silent"),
        key="weak",
        value={"text": "maybe purple", "kind": "fact", "confidence": 0.2},
    )
    bundle = await recall_for_thread(
        port,
        thread_id="g1-silent",
        query="purple",
        min_confidence=0.7,
    )
    assert bundle.hits == ()
    assert bundle.as_prompt_block() == "(no durable memory)"


@pytest.mark.asyncio()
async def test_g1_error_compounding_extract_idempotent() -> None:
    """Duplicate extract enqueue must not multiply jobs (Error Compounding)."""
    queue = InMemoryExtractJobQueue(max_queue=8)
    assert await queue.enqueue(thread_id="g1-ec", task_id="same", user_id="u")
    assert await queue.enqueue(thread_id="g1-ec", task_id="same", user_id="u")
    stats = await queue.stats()
    assert stats.depth == 1


@pytest.mark.asyncio()
async def test_g1_storage_exhaustion_queue_cap() -> None:
    """Queue at capacity rejects new work (Storage Exhaustion)."""
    queue = InMemoryExtractJobQueue(max_queue=1)
    assert await queue.enqueue(thread_id="g1-se", task_id="a")
    assert await queue.enqueue(thread_id="g1-se", task_id="b") is False


@pytest.mark.asyncio()
async def test_m7_recall_at_k_above_slo() -> None:
    """Offline Recall@4 on a fixed fixture must stay ≥ 0.85 (SLO §15 / M7)."""
    port = InMemoryMemoryPort()
    # (query_token, entry_key, text) — unique tokens so noise cannot dominate ranking.
    cases: list[tuple[str, str, str]] = [
        ("duckdbnx", "duck-dinner", "User prefers duckdbnx for dinner"),
        ("rusklangz", "lang-ru", "User prefers rusklangz responses"),
        ("mdtablezx", "fmt-table", "User wants answers as mdtablezx"),
        ("acmeivanx", "entity-acme", "Acme legal owner is acmeivanx"),
        ("utcschedz", "tz-utc", "Meetings should use utcschedz"),
        ("quietnotz", "noise-mode", "Prefer quietnotz notifications"),
        ("pydtypedz", "style-py", "Prefer pydtypedz Python models"),
        ("hitlwritz", "policy-hitl", "Irreversible writes need hitlwritz"),
    ]
    for idx in range(12):
        await port.put(
            namespace=user_namespace("eval-rk"),
            key=f"noise-{idx}",
            value={
                "text": f"Unrelated filler note number {idx} about weather",
                "kind": "fact",
                "confidence": 0.95,
                "importance": 0.2,
            },
        )
    for _token, key, text in cases:
        await port.put(
            namespace=user_namespace("eval-rk"),
            key=key,
            value={"text": text, "kind": "fact", "confidence": 0.95, "importance": 0.95},
        )

    scores: list[float] = []
    k = 4
    for token, gold_key, gold_text in cases:
        bundle = await recall_for_thread(
            port,
            thread_id=f"rk-{gold_key}",
            user_id="eval-rk",
            query=token,
            limit=k,
            min_confidence=0.7,
        )
        retrieved_keys = [gold_key for hit in bundle.hits if hit.text == gold_text]
        # Fallback: token still present in hit text.
        if not retrieved_keys:
            retrieved_keys = [gold_key for hit in bundle.hits if token in hit.text.lower()]
        scores.append(
            recall_at_k(retrieved_keys=retrieved_keys, relevant_keys=frozenset({gold_key}), k=k)
        )

    mean = mean_recall_at_k(scores)
    agent_metrics.record_memory_recall_at_k(k=k, value=mean)
    assert mean >= 0.85, f"Recall@{k}={mean:.3f} below SLO 0.85; scores={scores}"


def test_recall_at_k_pure() -> None:
    assert recall_at_k(retrieved_keys=["a", "b", "c"], relevant_keys=frozenset({"a", "c"}), k=2) == 0.5
    assert recall_at_k(retrieved_keys=["a", "b"], relevant_keys=frozenset({"a"}), k=1) == 1.0
    assert recall_at_k(retrieved_keys=[], relevant_keys=frozenset({"a"}), k=4) == 0.0


def test_g7_faithfulness_and_precision_pure() -> None:
    """Deterministic G7 lite — no LLM judge (plan: optional judge stays non-CI)."""
    corpus = frozenset({"User prefers duck for dinner", "Meetings in UTC"})
    assert faithfulness_grounded(hint_texts=["User prefers duck for dinner"], corpus_texts=corpus) == 1.0
    assert faithfulness_grounded(hint_texts=["Invented alien fact"], corpus_texts=corpus) == 0.0
    assert context_precision_at_k(
        retrieved_keys=["gold", "noise"],
        relevant_keys=frozenset({"gold"}),
        k=2,
    ) == 0.5


@pytest.mark.asyncio()
async def test_g7_recall_hints_are_faithful_to_corpus() -> None:
    """Recalled prompt hints must be grounded in stored medium texts (anti-hallucination)."""
    port = InMemoryMemoryPort()
    corpus = {
        "gold-a": "Canonical preference: tables over bullets",
        "gold-b": "Canonical timezone preference is Europe/Minsk",
        "noise": "Weather filler unrelated to the query tokens",
    }
    for key, text in corpus.items():
        await port.put(
            namespace=user_namespace("g7-faith"),
            key=key,
            value={"text": text, "kind": "fact", "confidence": 0.95, "importance": 0.9},
        )
    bundle = await recall_for_thread(
        port,
        thread_id="g7-faith-t",
        user_id="g7-faith",
        query="tables timezone",
        limit=4,
        min_confidence=0.7,
    )
    score = faithfulness_grounded(
        hint_texts=list(bundle.hint_texts),
        corpus_texts=frozenset(corpus.values()),
    )
    assert score >= 0.85, f"faithfulness={score:.3f} hints={bundle.hint_texts}"

    # Precision: map hits back to keys via exact text.
    key_by_text = {text: key for key, text in corpus.items()}
    retrieved = [key_by_text[h.text] for h in bundle.hits if h.text in key_by_text]
    precision = context_precision_at_k(
        retrieved_keys=retrieved,
        relevant_keys=frozenset({"gold-a", "gold-b"}),
        k=4,
    )
    assert precision >= 0.80, f"context_precision={precision:.3f} retrieved={retrieved}"


def test_m7_promote_error_and_recall_metric_apis() -> None:
    """Registry methods are callable (Prom or Noop); no exception on publish path."""
    agent_metrics.record_memory_promote_error(error_type="ValueError")
    agent_metrics.record_memory_recall_at_k(k=4, value=0.91)
