# src/palatium_ai/infrastructure/graph/in_memory_graph_write_port.py

"""In-memory GraphWritePort for tests / stub promote path."""

from __future__ import annotations

import hashlib

from palatium_ai.domain.graph.write_port import GraphFactUpsert


class InMemoryGraphWritePort:
    """Stores upserted facts in-process (dev/tests)."""

    def __init__(self) -> None:
        self.facts: dict[str, GraphFactUpsert] = {}

    async def upsert_fact(self, command: GraphFactUpsert) -> str:
        node_id = hashlib.sha256(f"{command.user_id}:{command.entry_key}".encode()).hexdigest()[:24]
        self.facts[node_id] = command
        return node_id
