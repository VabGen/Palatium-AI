"""Unit tests for Mem0 MemoryPort adapter (fake transport)."""

from __future__ import annotations

import pytest

from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.infrastructure.memory.mem0_adapter import Mem0MemoryPort, namespace_to_scope


class _FakeMem0Transport:
    def __init__(self) -> None:
        self.adds: list[dict[str, object]] = []
        self._hits: list[dict[str, object]] = []

    async def add_memory(
        self,
        *,
        text: str,
        scope: dict[str, str],
        metadata: dict[str, object],
    ) -> str | None:
        self.adds.append({"text": text, "scope": scope, "metadata": metadata})
        self._hits.append(
            {
                "text": text,
                "kind": metadata.get("kind", "fact"),
                "confidence": metadata.get("confidence", 0.8),
                "_score": 1.0,
                "palatium_key": metadata.get("palatium_key", ""),
            }
        )
        return "evt-1"

    async def search_memories(
        self,
        *,
        query: str,
        scope: dict[str, str],
        limit: int,
    ) -> list[dict[str, object]]:
        _ = scope
        tokens = query.lower().split()
        matched = [
            hit
            for hit in self._hits
            if (
                any(token in str(hit["text"]).lower() for token in tokens)
                or any(token in str(hit.get("palatium_key", "")).lower() for token in tokens)
                or not tokens
            )
        ]
        return matched[:limit]

    async def aclose(self) -> None:
        return None


def test_namespace_to_scope_mapping() -> None:
    assert namespace_to_scope(user_namespace("u1")) == {"user_id": "u1"}
    assert namespace_to_scope(org_namespace("acme")) == {"agent_id": "org:acme"}
    assert namespace_to_scope(thread_namespace("t1")) == {"run_id": "t1"}


@pytest.mark.asyncio
async def test_mem0_port_put_search_get() -> None:
    transport = _FakeMem0Transport()
    port = Mem0MemoryPort(transport)
    await port.put(
        namespace=user_namespace("user-1"),
        key="pref-tables",
        value={"text": "User prefers markdown tables", "kind": "preference", "confidence": 0.95},
    )
    assert transport.adds
    assert transport.adds[0]["scope"] == {"user_id": "user-1"}

    hits = await port.search(namespace=user_namespace("user-1"), query="tables", limit=4)
    assert hits
    assert "tables" in str(hits[0]["text"]).lower()

    got = await port.get(namespace=user_namespace("user-1"), key="pref-tables")
    assert got is not None
    assert got["kind"] == "preference"
