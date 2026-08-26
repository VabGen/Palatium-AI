"""Budgeted memory recall helpers."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.domain.memory.recall import MemoryHit, MemoryRecallBundle
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


def test_recall_bundle_respects_char_budget() -> None:
    hits = tuple(MemoryHit(text=f"fact-{idx}-" + ("x" * 200), kind="fact", confidence=0.9, score=1) for idx in range(6))
    bundle = MemoryRecallBundle(thread_id="t", hits=hits, max_items=4, max_chars=300)
    block = bundle.as_prompt_block()
    assert len(block) <= 300
    assert block.startswith("- [fact]")


@pytest.mark.asyncio
async def test_recall_for_thread_searches_namespace() -> None:
    port = InMemoryMemoryPort()
    await port.put(
        namespace=thread_namespace("t1"),
        key="k1",
        value={"text": "User prefers markdown tables", "kind": "preference", "confidence": 0.95},
    )
    bundle = await recall_for_thread(port, thread_id="t1", query="tables format", limit=4)
    assert bundle.hits
    assert "tables" in bundle.hits[0].text.lower() or "markdown" in bundle.hits[0].text.lower()
    assert bundle.hint_texts


@pytest.mark.asyncio
async def test_recall_drops_low_confidence_hits() -> None:
    port = InMemoryMemoryPort()
    await port.put(
        namespace=thread_namespace("t2"),
        key="noisy",
        value={"text": "maybe likes tables", "kind": "fact", "confidence": 0.2},
    )
    await port.put(
        namespace=thread_namespace("t2"),
        key="solid",
        value={"text": "prefers tables for agendas", "kind": "preference", "confidence": 0.9},
    )
    bundle = await recall_for_thread(
        port,
        thread_id="t2",
        query="tables agenda",
        limit=4,
        min_confidence=0.7,
    )
    assert len(bundle.hits) == 1
    assert bundle.hits[0].confidence >= 0.7


@pytest.mark.asyncio
async def test_recall_merges_user_namespace_preferences() -> None:
    port = InMemoryMemoryPort()
    await port.put(
        namespace=thread_namespace("t3"),
        key="ephemeral",
        value={"text": "thread-only meeting note", "kind": "fact", "confidence": 0.9},
    )
    await port.put(
        namespace=user_namespace("user-1"),
        key="pref",
        value={"text": "User prefers tables", "kind": "preference", "confidence": 0.95},
    )
    bundle = await recall_for_thread(
        port,
        thread_id="t3",
        user_id="user-1",
        query="tables format",
        limit=4,
    )
    kinds = {hit.kind for hit in bundle.hits}
    texts = " ".join(hit.text.lower() for hit in bundle.hits)
    assert "preference" in kinds or "tables" in texts


@pytest.mark.asyncio
async def test_recall_merges_org_namespace_entities() -> None:
    port = InMemoryMemoryPort()
    await port.put(
        namespace=org_namespace("org-acme"),
        key="entity",
        value={"text": "Acme legal contact is Ivanova", "kind": "entity", "confidence": 0.92},
    )
    without_org = await recall_for_thread(
        port,
        thread_id="t4",
        query="Acme contact",
        limit=4,
    )
    assert without_org.hits == ()

    with_org = await recall_for_thread(
        port,
        thread_id="t4",
        org_id="org-acme",
        query="Acme contact",
        limit=4,
    )
    assert with_org.hits
    assert "ivanova" in with_org.hits[0].text.lower() or "acme" in with_org.hits[0].text.lower()
