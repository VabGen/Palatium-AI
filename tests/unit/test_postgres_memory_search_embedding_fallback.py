from __future__ import annotations

import pytest

from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort


class _UnavailableEmbeddings:
    async def embed(self, texts: list[str], *, model: str | None = None) -> list[list[float]]:
        raise RuntimeError("embedding provider unavailable")


@pytest.mark.asyncio()
async def test_search_falls_back_to_fts_when_embedding_provider_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    port = PostgresMemoryPort(object(), embeddings=_UnavailableEmbeddings())  # type: ignore[arg-type]
    fts_hit = {
        "_entry_key": "fts-hit",
        "text": "matching text",
        "kind": "fact",
        "confidence": 0.9,
        "importance": 0.8,
    }

    async def fake_search_fts(**_: object) -> list[tuple[str, float, dict[str, object]]]:
        return [("fts-hit", 0.9, fts_hit)]

    monkeypatch.setattr(port, "_search_fts", fake_search_fts)

    results = await port.search(namespace=("user", "test-user"), query="matching", limit=4)

    assert [item["_entry_key"] for item in results] == ["fts-hit"]
    assert results[0]["text"] == "matching text"
