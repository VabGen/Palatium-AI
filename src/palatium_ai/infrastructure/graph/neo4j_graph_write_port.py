# src/palatium_ai/infrastructure/graph/neo4j_graph_write_port.py

"""Neo4j GraphWritePort — parameterized MERGE for promote (060 / 020 EXCEPTION at call site)."""

from __future__ import annotations

import hashlib

from typing import Protocol

from palatium_ai.domain.graph.write_port import GraphFactUpsert

# Fixed template — never f-string user text into Cypher (070 / 020).
_UPSERT_FACT_CYPHER = """
MERGE (f:MemoryFact {user_id: $user_id, entry_key: $entry_key})
ON CREATE SET
  f.node_id = $node_id,
  f.text = $text,
  f.kind = $kind,
  f.importance = $importance,
  f.thread_id = $thread_id,
  f.source_namespace = $source_namespace,
  f.created_at = datetime()
ON MATCH SET
  f.text = $text,
  f.kind = $kind,
  f.importance = $importance,
  f.thread_id = $thread_id,
  f.source_namespace = $source_namespace,
  f.updated_at = datetime()
RETURN f.node_id AS node_id
""".strip()


class Neo4jWriteTransport(Protocol):
    """Minimal async write surface (injectable in tests)."""

    async def run_write(
        self,
        *,
        cypher: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        """Execute parameterized write Cypher; return result rows."""

    async def aclose(self) -> None:
        """Close driver / pool resources."""


class Neo4jGraphWritePort:
    """Upsert long-term MemoryFact nodes via MERGE (promote path)."""

    def __init__(self, transport: Neo4jWriteTransport) -> None:
        self._transport = transport

    async def upsert_fact(self, command: GraphFactUpsert) -> str:
        node_id = _stable_node_id(command.user_id, command.entry_key)
        params: dict[str, object] = {
            "user_id": command.user_id,
            "entry_key": command.entry_key,
            "node_id": node_id,
            "text": command.text,
            "kind": command.kind,
            "importance": float(command.importance),
            "thread_id": command.thread_id,
            "source_namespace": "/".join(command.source_namespace),
        }
        rows = await self._transport.run_write(cypher=_UPSERT_FACT_CYPHER, params=params)
        if rows:
            returned = rows[0].get("node_id")
            if isinstance(returned, str) and returned.strip():
                return returned.strip()
        return node_id

    async def aclose(self) -> None:
        await self._transport.aclose()


def _stable_node_id(user_id: str, entry_key: str) -> str:
    return hashlib.sha256(f"{user_id}:{entry_key}".encode()).hexdigest()[:24]
