"""Embedding hybrid rerank over lexical MemoryPort hits."""

from __future__ import annotations

import pytest

from palatium_ai.domain.memory.namespaces import thread_namespace
from palatium_ai.infrastructure.memory.embedding_rerank import EmbeddingRerankMemoryPort, _cosine
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


class _FakeEmbeddings:
    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        _ = model
        # Map keywords into orthogonal axes so "tables" beats unrelated text.
        vectors: list[list[float]] = []
        for text in texts:
            lower = text.lower()
            vectors.append(
                [
                    1.0 if "table" in lower or "таблиц" in lower else 0.0,
                    1.0 if "meeting" in lower or "встреч" in lower else 0.0,
                    1.0 if "unrelated" in lower else 0.0,
                ]
            )
        return vectors


def test_cosine_identical() -> None:
    assert _cosine([1.0, 0.0], [1.0, 0.0]) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_embedding_rerank_prefers_semantic_match() -> None:
    inner = InMemoryMemoryPort()
    ns = thread_namespace("t-rerank")
    await inner.put(
        namespace=ns,
        key="a",
        value={"text": "completely unrelated note", "kind": "fact", "confidence": 0.95},
    )
    await inner.put(
        namespace=ns,
        key="b",
        value={"text": "user prefers tables for meeting agendas", "kind": "preference", "confidence": 0.9},
    )
    port = EmbeddingRerankMemoryPort(inner, _FakeEmbeddings())  # type: ignore[arg-type]
    hits = await port.search(namespace=ns, query="tables for meetings", limit=2)
    assert hits
    assert "tables" in str(hits[0]["text"]).lower()
