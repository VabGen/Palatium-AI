"""L3+L4 fusion in recall_for_thread (Super Brain SB3)."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort


class _StubMemoryPort:
    async def search(self, *, namespace: tuple[str, ...], query: str, limit: int = 8) -> list[dict[str, object]]:
        _ = (namespace, query, limit)
        return [
            {
                "text": "medium fact about tea",
                "kind": "fact",
                "confidence": 0.9,
                "_score": 0.9,
                "_entry_key": "m1",
            }
        ]

    async def bump_access(self, *, namespace: tuple[str, ...], key: str) -> None:
        _ = (namespace, key)


@pytest.mark.asyncio()
async def test_recall_fuses_graph_active_facts() -> None:
    graph = InMemoryGraphWritePort()
    await graph.upsert_fact(
        GraphFactUpsert(
            user_id="u1",
            entry_key="name",
            text="User name is Gennadiy",
            kind="preference",
            importance=0.95,
            confidence=0.95,
            thread_id="t1",
        )
    )
    bundle = await recall_for_thread(
        _StubMemoryPort(),  # type: ignore[arg-type]
        thread_id="t1",
        query="who am I",
        user_id="u1",
        limit=4,
        min_confidence=0.7,
        graph_write=graph,
    )
    texts = {h.text for h in bundle.hits}
    sources = {h.source for h in bundle.hits}
    assert "medium fact about tea" in texts
    assert "User name is Gennadiy" in texts
    assert "medium" in sources
    assert "graph" in sources
