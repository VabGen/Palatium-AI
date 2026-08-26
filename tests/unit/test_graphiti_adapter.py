"""Unit tests for Graphiti MemoryPort adapter (fake transport)."""

from __future__ import annotations

from datetime import datetime

import pytest

from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace
from palatium_ai.infrastructure.memory.graphiti_adapter import (
    GraphitiMemoryPort,
    namespace_to_group_id,
)


class _FakeGraphitiTransport:
    def __init__(self) -> None:
        self.episodes: list[dict[str, object]] = []
        self._facts: list[dict[str, object]] = []

    async def add_episode(
        self,
        *,
        name: str,
        body: str,
        group_id: str,
        reference_time: datetime,
        source_description: str,
    ) -> str | None:
        self.episodes.append(
            {
                "name": name,
                "body": body,
                "group_id": group_id,
                "reference_time": reference_time,
                "source_description": source_description,
            }
        )
        self._facts.append(
            {
                "text": body,
                "kind": "entity",
                "confidence": 0.85,
                "_score": 1.0,
                "group_id": group_id,
            }
        )
        return "ep-1"

    async def search(self, *, query: str, group_id: str, limit: int) -> list[dict[str, object]]:
        tokens = query.lower().split()
        matched = [
            fact
            for fact in self._facts
            if fact.get("group_id") == group_id
            and (any(token in str(fact["text"]).lower() for token in tokens) or not tokens)
        ]
        return matched[:limit]

    async def aclose(self) -> None:
        return None


def test_namespace_to_group_id() -> None:
    assert namespace_to_group_id(user_namespace("u1")) == "user:u1"
    assert namespace_to_group_id(org_namespace("acme")) == "org:acme"
    assert namespace_to_group_id(thread_namespace("t1")) == "thread:t1"


@pytest.mark.asyncio
async def test_graphiti_port_put_search() -> None:
    transport = _FakeGraphitiTransport()
    port = GraphitiMemoryPort(transport)
    await port.put(
        namespace=org_namespace("acme"),
        key="acme-legal",
        value={"text": "Acme legal contact is Ivanova", "kind": "entity", "confidence": 0.9},
    )
    assert transport.episodes
    assert transport.episodes[0]["group_id"] == "org:acme"

    hits = await port.search(namespace=org_namespace("acme"), query="Ivanova legal", limit=4)
    assert hits
    assert "ivanova" in str(hits[0]["text"]).lower()

    # Cross-tenant isolation: other org group sees nothing.
    other = await port.search(namespace=org_namespace("other"), query="Ivanova", limit=4)
    assert other == []
