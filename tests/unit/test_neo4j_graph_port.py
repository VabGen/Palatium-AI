"""Unit tests for Neo4j GraphPort."""

from __future__ import annotations

import pytest

from palatium_ai.domain.graph.temporal import ACTIVE_FACT_AS_OF_PREDICATE
from palatium_ai.domain.graph.types import GraphQueryCommand
from palatium_ai.infrastructure.graph.neo4j_graph_port import Neo4jGraphPort


class _FakeNeo4jTransport:
    def __init__(self, rows: list[dict[str, object]] | None = None) -> None:
        self.rows = rows or [{"fact": "Palatium uses layered architecture", "user_id": "u1"}]
        self.last_query: tuple[str, dict[str, object], int] | None = None
        self.closed = False

    async def run_query(
        self,
        *,
        cypher: str,
        params: dict[str, object],
        limit: int,
    ) -> list[dict[str, object]]:
        self.last_query = (cypher, params, limit)
        return self.rows[:limit]

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio()
async def test_neo4j_graph_port_serializes_rows() -> None:
    transport = _FakeNeo4jTransport()
    port = Neo4jGraphPort(transport)
    result = await port.query(
        GraphQueryCommand(
            user_id="u1",
            cypher="MATCH (f:Fact {user_id: $user_id}) RETURN f.text AS fact LIMIT $lim",
            params={"user_id": "u1", "lim": 5},
            limit=5,
        )
    )
    assert result.row_count == 1
    assert result.rows[0].values["fact"] == "Palatium uses layered architecture"
    assert transport.last_query is not None
    assert transport.last_query[1]["user_id"] == "u1"


@pytest.mark.asyncio()
async def test_neo4j_graph_port_rejects_write_cypher() -> None:
    port = Neo4jGraphPort(_FakeNeo4jTransport())
    with pytest.raises(ValueError, match="read-only"):
        await port.query(
            GraphQueryCommand(
                user_id="u1",
                cypher="MATCH (n) DELETE n RETURN n",
                params={},
            )
        )


@pytest.mark.asyncio()
async def test_neo4j_graph_port_rejects_unscoped_cypher() -> None:
    """070: an unscoped read must never reach the driver (cross-tenant leak)."""
    port = Neo4jGraphPort(_FakeNeo4jTransport())
    with pytest.raises(ValueError, match="tenant"):
        await port.query(
            GraphQueryCommand(
                user_id="u1",
                cypher="MATCH (n) RETURN n LIMIT $lim",
                params={"lim": 5},
                limit=5,
            )
        )


@pytest.mark.asyncio()
async def test_neo4j_graph_port_forces_tenant_param() -> None:
    """Client-supplied user_id in params must be overwritten by the authenticated user (020)."""
    transport = _FakeNeo4jTransport()
    port = Neo4jGraphPort(transport)
    await port.query(
        GraphQueryCommand(
            user_id="u-actor",
            cypher="MATCH (f:Fact {user_id: $user_id}) RETURN f.text AS fact LIMIT $lim",
            params={"user_id": "u-victim", "lim": 5},
            limit=5,
        )
    )
    assert transport.last_query is not None
    assert transport.last_query[1]["user_id"] == "u-actor"


@pytest.mark.asyncio()
async def test_neo4j_graph_port_binds_as_of_by_default() -> None:
    """M5: every read carries a time anchor, even when the caller did not ask for one."""
    transport = _FakeNeo4jTransport()
    port = Neo4jGraphPort(transport)
    await port.query(
        GraphQueryCommand(
            user_id="u1",
            cypher="MATCH (f:Fact {user_id: $user_id}) RETURN f.text AS fact",
            params={},
        )
    )
    assert transport.last_query is not None
    as_of = transport.last_query[1]["as_of"]
    assert isinstance(as_of, str)
    assert as_of.endswith("Z")


@pytest.mark.asyncio()
async def test_neo4j_graph_port_binds_requested_as_of() -> None:
    from datetime import UTC, datetime

    transport = _FakeNeo4jTransport()
    port = Neo4jGraphPort(transport)
    await port.query(
        GraphQueryCommand(
            user_id="u1",
            cypher=("MATCH (f:MemoryFact) WHERE " + ACTIVE_FACT_AS_OF_PREDICATE + " RETURN f.text AS fact"),
            params={"lim": 5},
            as_of=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
        )
    )
    assert transport.last_query is not None
    assert transport.last_query[1]["as_of"] == "2026-01-02T03:04:05Z"


@pytest.mark.asyncio()
async def test_neo4j_graph_port_rejects_fact_read_without_as_of() -> None:
    """M5 audit F1: the driver must never see an unfiltered ``:MemoryFact`` read."""
    port = Neo4jGraphPort(_FakeNeo4jTransport())
    with pytest.raises(ValueError, match="as_of"):
        await port.query(
            GraphQueryCommand(
                user_id="u1",
                cypher="MATCH (f:MemoryFact {user_id: $user_id}) RETURN f.text AS fact",
                params={},
            )
        )


@pytest.mark.asyncio()
async def test_neo4j_graph_port_closes_transport() -> None:
    transport = _FakeNeo4jTransport()
    port = Neo4jGraphPort(transport)
    await port.aclose()
    assert transport.closed is True
