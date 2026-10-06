# tests/unit/test_neo4j_graph_write_port.py

"""Neo4j GraphWritePort — parameterized MERGE for promote."""

from __future__ import annotations

import pytest

from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.infrastructure.graph.factory import build_graph_write_port
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.graph.neo4j_graph_write_port import Neo4jGraphWritePort, _stable_node_id


class _FakeWriteTransport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    async def run_write(self, *, cypher: str, params: dict[str, object]) -> list[dict[str, object]]:
        self.calls.append((cypher, dict(params)))
        return [{"node_id": params["node_id"]}]

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio()
async def test_upsert_fact_uses_parameterized_merge() -> None:
    transport = _FakeWriteTransport()
    port = Neo4jGraphWritePort(transport)
    command = GraphFactUpsert(
        user_id="alice",
        entry_key="pref-duck",
        text="User prefers duck for dinner",
        kind="preference",
        importance=0.91,
        source_namespace=("user", "alice"),
        thread_id="",
    )
    node_id = await port.upsert_fact(command)
    assert node_id == _stable_node_id("alice", "pref-duck")
    assert len(transport.calls) == 1
    cypher, params = transport.calls[0]
    assert "MERGE (f:MemoryFact" in cypher
    assert "$user_id" in cypher
    assert "$text" in cypher
    assert "alice" not in cypher  # no string concat of user data
    assert params["user_id"] == "alice"
    assert params["entry_key"] == "pref-duck"
    assert params["text"] == "User prefers duck for dinner"
    assert params["kind"] == "preference"
    assert params["importance"] == 0.91
    assert params["source_namespace"] == "user/alice"


@pytest.mark.asyncio()
async def test_upsert_fact_idempotent_stable_id() -> None:
    transport = _FakeWriteTransport()
    port = Neo4jGraphWritePort(transport)
    command = GraphFactUpsert(
        user_id="u1",
        entry_key="k1",
        text="same fact",
        kind="fact",
        importance=0.8,
    )
    first = await port.upsert_fact(command)
    second = await port.upsert_fact(command)
    assert first == second
    assert len(transport.calls) == 2


def test_build_graph_write_port_defaults_to_in_memory() -> None:
    class _Mem:
        graph_query_backend = "in_memory"
        graphiti_neo4j_uri = "bolt://localhost:7687"
        graphiti_neo4j_user = "neo4j"
        graphiti_neo4j_password = None

    class _Settings:
        memory = _Mem()

    port = build_graph_write_port(_Settings())  # type: ignore[arg-type]
    assert isinstance(port, InMemoryGraphWritePort)
