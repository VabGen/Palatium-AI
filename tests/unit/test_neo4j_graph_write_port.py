# tests/unit/test_neo4j_graph_write_port.py

"""Neo4j GraphWritePort — bi-temporal FIND/CREATE/SUPERSEDE/EXPIRE (Wave M5)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.infrastructure.graph.factory import build_graph_write_port
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.graph.neo4j_graph_write_port import Neo4jGraphWritePort, _stable_node_id


class _FakeWriteTransport:
    """Records Cypher calls; FIND returns optional active row, MAX returns the version."""

    def __init__(self, *, find_row: dict[str, object] | None = None, max_version: int = 0) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self._find_row = find_row
        self._max_version = max_version

    async def run_write(self, *, cypher: str, params: dict[str, object]) -> list[dict[str, object]]:
        self.calls.append((cypher, dict(params)))
        if "AS max_version" in cypher:
            return [{"max_version": self._max_version}]
        if "RETURN f.text AS text" in cypher and "MERGE" not in cypher:
            return [self._find_row] if self._find_row is not None else []
        if "RETURN count(f) AS n" in cypher:
            return [{"n": 1}]
        if "SET f.hebbian_weight" in cypher:
            return [{"hebbian_weight": params.get("hebbian_weight")}]
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
    assert len(transport.calls) == 3
    find_cypher, find_params = transport.calls[0]
    max_cypher, max_params = transport.calls[1]
    create_cypher, create_params = transport.calls[2]
    assert "MATCH (f:MemoryFact" in find_cypher
    assert "AS max_version" in max_cypher
    assert max_params == {"user_id": "alice", "entry_key": "pref-duck"}
    # MERGE, not CREATE: a retried or concurrent write of the same version must converge
    # on one node instead of adding a twin active fact (M5 audit F6).
    assert "MERGE (f:MemoryFact {node_id: $node_id})" in create_cypher
    assert "CREATE (f:MemoryFact" not in create_cypher
    assert "ON CREATE SET" in create_cypher
    assert "ON MATCH SET" in create_cypher
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
    assert create_params["sentinel"] == "9999-12-31T23:59:59Z"
    assert "datetime($sentinel)" in create_cypher


@pytest.mark.asyncio()
async def test_upsert_fact_refresh_same_text() -> None:
    old_id = _stable_node_id("u1", "k1", 1)
    transport = _FakeWriteTransport(find_row={"text": "same fact", "node_id": old_id, "version": 1, "contains_pii": False})
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
    transport = _FakeWriteTransport(find_row={"text": "old truth", "node_id": old_id, "version": 1, "contains_pii": False})
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
async def test_supersede_cuts_valid_time_at_the_new_fact_not_at_now() -> None:
    """F2: ``invalid_at`` is the new fact's ``valid_at``, not the wall clock.

    With ``datetime()`` a backdated write leaves ``[new.valid_at, now)`` where both
    versions are active, so ``as_of`` reads return contradictory texts.
    """
    old_id = _stable_node_id("u1", "k1", 1)
    transport = _FakeWriteTransport(find_row={"text": "old truth", "node_id": old_id, "version": 1, "contains_pii": False})
    port = Neo4jGraphWritePort(transport)
    backdated = datetime(2026, 1, 15, 9, 30, tzinfo=UTC)

    await port.upsert_fact(GraphFactUpsert(user_id="u1", entry_key="k1", text="new truth", kind="fact", valid_at=backdated))

    supersede_cypher, params = transport.calls[1]
    assert "old.invalid_at = datetime($valid_at)" in supersede_cypher
    assert params["valid_at"] == "2026-01-15T09:30:00Z"


def test_find_active_treats_a_future_invalid_at_as_still_current() -> None:
    """A scheduled supersede must not hide the current fact from the next write.

    ``invalid_at IS NULL`` alone would drop a future-dated row from FIND, so the
    following upsert would CREATE a second version instead of superseding — one key,
    two live facts.
    """
    from palatium_ai.infrastructure.graph.neo4j_graph_write_port import _FIND_ACTIVE_CYPHER

    assert "(f.invalid_at IS NULL OR f.invalid_at > datetime())" in _FIND_ACTIVE_CYPHER
    assert "(f.expired_at IS NULL OR f.expired_at > datetime())" in _FIND_ACTIVE_CYPHER


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


@pytest.mark.asyncio()
async def test_bump_hebbian_on_entry_reads_then_sets_weight() -> None:
    old_id = _stable_node_id("u1", "k1", 1)
    transport = _FakeWriteTransport(
        find_row={
            "text": "fact",
            "node_id": old_id,
            "version": 1,
            "contains_pii": False,
            "hebbian_weight": 0.5,
        }
    )
    port = Neo4jGraphWritePort(transport)
    weight = await port.bump_hebbian_on_entry(user_id="u1", entry_key="k1")
    assert weight == pytest.approx(0.55)
    assert len(transport.calls) == 2
    find_cypher, find_params = transport.calls[0]
    set_cypher, set_params = transport.calls[1]
    assert "hebbian_weight" in find_cypher
    assert find_params == {"user_id": "u1", "entry_key": "k1"}
    assert "SET f.hebbian_weight" in set_cypher
    assert set_params["node_id"] == old_id
    assert set_params["hebbian_weight"] == pytest.approx(0.55)


@pytest.mark.asyncio()
async def test_bump_hebbian_on_entry_without_active_fact_returns_zero() -> None:
    transport = _FakeWriteTransport()
    port = Neo4jGraphWritePort(transport)
    assert await port.bump_hebbian_on_entry(user_id="u1", entry_key="missing") == 0.0
    assert len(transport.calls) == 1  # FIND only


@pytest.mark.asyncio()
async def test_bump_hebbian_on_entry_ignores_blank_keys() -> None:
    transport = _FakeWriteTransport()
    port = Neo4jGraphWritePort(transport)
    assert await port.bump_hebbian_on_entry(user_id="  ", entry_key="k1") == 0.0
    assert transport.calls == []


@pytest.mark.asyncio()
async def test_list_active_facts_without_thread_has_no_thread_predicate() -> None:
    """No thread → no thread predicate at all.

    The previous ``$thread_id = '' OR ...`` disjunction forbade index use and scanned
    every ``MemoryFact``; an absent predicate keeps the single ``user_id`` seek (080).
    """
    transport = _FakeWriteTransport()
    port = Neo4jGraphWritePort(transport)

    await port.list_active_facts(user_id="u1", limit=4)

    cypher, params = transport.calls[0]
    assert "thread_id" not in cypher
    assert "thread_id" not in params
    assert "$user_id" in cypher
    assert "datetime($as_of)" in cypher


@pytest.mark.asyncio()
async def test_list_active_facts_with_thread_uses_indexed_equality() -> None:
    """A bound thread is an equality on the composite index, not an OR chain."""
    transport = _FakeWriteTransport()
    port = Neo4jGraphWritePort(transport)

    await port.list_active_facts(user_id="u1", limit=4, thread_id="t-1")

    cypher, params = transport.calls[0]
    assert "f.thread_id = $thread_id" in cypher
    assert "f.thread_id IS NULL" not in cypher
    assert "$thread_id = ''" not in cypher
    assert params["thread_id"] == "t-1"
    assert params["user_id"] == "u1"


@pytest.mark.asyncio()
async def test_create_after_expiry_starts_at_the_next_version() -> None:
    """A forgotten key keeps its history; restarting at version 1 would revive it.

    ``node_id`` is derived from the version, so reusing version 1 makes ``MERGE`` match
    the *expired* node — the new fact would be written onto a node that stays invisible
    to every ``as_of`` read.
    """
    transport = _FakeWriteTransport(max_version=3)
    port = Neo4jGraphWritePort(transport)

    node_id = await port.upsert_fact(GraphFactUpsert(user_id="u1", entry_key="k1", text="fresh statement", kind="fact"))

    assert node_id == _stable_node_id("u1", "k1", 4)
    assert transport.calls[-1][1]["version"] == 4


def test_merge_keeps_the_lifecycle_of_an_existing_version() -> None:
    """``ON MATCH`` may refresh content but must not rewrite valid/expired timestamps."""
    from palatium_ai.infrastructure.graph.neo4j_graph_write_port import _CREATE_CYPHER, _SUPERSEDE_CYPHER

    on_match = _CREATE_CYPHER.split("ON MATCH SET")[1]
    for lifecycle in ("f.valid_at", "f.created_at", "f.expired_at", "f.invalid_at"):
        assert lifecycle not in on_match
    assert "MERGE (f)-[:SUPERSEDES]->(old)" in _SUPERSEDE_CYPHER
    assert "CREATE (f)-[:SUPERSEDES]" not in _SUPERSEDE_CYPHER


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
