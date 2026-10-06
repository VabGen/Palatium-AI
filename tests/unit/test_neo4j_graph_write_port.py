# tests/unit/test_neo4j_graph_write_port.py

"""Neo4j GraphWritePort — bi-temporal FIND/CREATE/SUPERSEDE/EXPIRE (Wave M5)."""

from __future__ import annotations

import pytest

from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.infrastructure.graph.factory import build_graph_write_port
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.graph.neo4j_graph_write_port import Neo4jGraphWritePort, _stable_node_id


class _FakeWriteTransport:
    """Records Cypher calls; FIND returns optional active row."""

    def __init__(self, *, find_row: dict[str, object] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._find_row = find_row

    async def run_write(self, *, cypher: str, params: dict[str, object]) -> list[dict[str, object]]:
        self.calls.append((cypher, dict(params)))
        if "WHERE f.invalid_at IS NULL AND f.expired_at IS NULL" in cypher:
            return [self._find_row] if self._find_row is not None else []
        if "RETURN count(f) AS n" in cypher:
            return [{"n": 1}]
        node_id = params.get("node_id") or params.get("old_node_id")
        return [{"node_id": node_id}]

    async def aclose(self) -> None:
        return None


@pytest.mark.asyncio()
async def test_upsert_fact_find_then_create_parameterized() -> None:
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
    assert node_id == _stable_node_id("alice", "pref-duck", 1)
    assert len(transport.calls) == 2
    find_cypher, find_params = transport.calls[0]
    create_cypher, create_params = transport.calls[1]
    assert "MATCH (f:MemoryFact" in find_cypher
    assert "CREATE (f:MemoryFact" in create_cypher
    assert "MERGE" not in create_cypher
    assert "$user_id" in create_cypher
    assert "$text" in create_cypher
    assert "alice" not in create_cypher
    assert find_params["user_id"] == "alice"
    assert create_params["entry_key"] == "pref-duck"
    assert create_params["text"] == "User prefers duck for dinner"
    assert create_params["kind"] == "preference"
    assert create_params["importance"] == 0.91
    assert create_params["source_namespace"] == "user/alice"
    assert create_params["version"] == 1


@pytest.mark.asyncio()
async def test_upsert_fact_refresh_same_text() -> None:
    old_id = _stable_node_id("u1", "k1", 1)
    transport = _FakeWriteTransport(
        find_row={"text": "same fact", "node_id": old_id, "version": 1, "contains_pii": False}
    )
    port = Neo4jGraphWritePort(transport)
    command = GraphFactUpsert(
        user_id="u1",
        entry_key="k1",
        text="same fact",
        kind="fact",
        importance=0.8,
    )
    node_id = await port.upsert_fact(command)
    assert node_id == old_id
    assert len(transport.calls) == 2
    assert "SET f.importance" in transport.calls[1][0]
    assert "CREATE" not in transport.calls[1][0]


@pytest.mark.asyncio()
async def test_upsert_fact_supersede_different_text() -> None:
    old_id = _stable_node_id("u1", "k1", 1)
    transport = _FakeWriteTransport(
        find_row={"text": "old truth", "node_id": old_id, "version": 1, "contains_pii": False}
    )
    port = Neo4jGraphWritePort(transport)
    command = GraphFactUpsert(
        user_id="u1",
        entry_key="k1",
        text="new truth",
        kind="fact",
        importance=0.8,
    )
    node_id = await port.upsert_fact(command)
    assert node_id == _stable_node_id("u1", "k1", 2)
    assert len(transport.calls) == 2
    supersede_cypher, params = transport.calls[1]
    assert "SUPERSEDES" in supersede_cypher
    assert "invalid_at" in supersede_cypher
    assert params["old_node_id"] == old_id
    assert params["text"] == "new truth"
    assert params["version"] == 2


@pytest.mark.asyncio()
async def test_upsert_fact_blocked_pii_semantic_flip() -> None:
    old_id = _stable_node_id("u1", "pii-1", 1)
    transport = _FakeWriteTransport(
        find_row={
            "text": "SSN is 123-45-6789",
            "node_id": old_id,
            "version": 1,
            "contains_pii": True,
        }
    )
    port = Neo4jGraphWritePort(transport)
    node_id = await port.upsert_fact(
        GraphFactUpsert(
            user_id="u1",
            entry_key="pii-1",
            text="SSN is 999-99-9999",
            kind="fact",
            contains_pii=True,
        )
    )
    assert node_id == ""
    assert len(transport.calls) == 1  # FIND only


@pytest.mark.asyncio()
async def test_expire_fact_sets_expired_at() -> None:
    transport = _FakeWriteTransport()
    port = Neo4jGraphWritePort(transport)
    assert await port.expire_fact(user_id="alice", entry_key="pref-duck") is True
    cypher, params = transport.calls[0]
    assert "expired_at" in cypher
    assert params["user_id"] == "alice"
    assert params["entry_key"] == "pref-duck"


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
