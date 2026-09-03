# src/palatium_ai/infrastructure/graph/neo4j_graph_port.py

"""Neo4j-backed GraphPort for ``graph_query`` (070)."""

from __future__ import annotations

import json

from typing import Protocol

from palatium_ai.domain.graph.cypher_safety import assert_params_cover_refs, assert_read_only_cypher
from palatium_ai.domain.graph.types import GraphQueryCommand, GraphQueryResult, GraphQueryRow


class Neo4jGraphTransport(Protocol):
    """Minimal async Neo4j surface (injectable in tests)."""

    async def run_query(
        self,
        *,
        cypher: str,
        params: dict[str, object],
        limit: int,
    ) -> list[dict[str, object]]:
        """Execute parameterized Cypher and return up to ``limit`` flat row dicts."""

    async def aclose(self) -> None:
        """Close driver / pool resources."""


class Neo4jDriverTransport:
    """Async Neo4j driver wrapper (optional ``neo4j`` package)."""

    def __init__(self, *, uri: str, user: str, password: str) -> None:
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError as exc:
            raise ImportError(
                "GRAPH_QUERY_BACKEND=neo4j requires the neo4j driver (poetry install --with graph)"
            ) from exc
        if not uri.strip() or not password:
            msg = "GRAPHITI_NEO4J_URI and GRAPHITI_NEO4J_PASSWORD are required for neo4j graph port"
            raise ValueError(msg)
        self._driver = AsyncGraphDatabase.driver(uri.strip(), auth=(user.strip() or "neo4j", password))

    async def run_query(
        self,
        *,
        cypher: str,
        params: dict[str, object],
        limit: int,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        async with self._driver.session() as session:
            result = await session.run(cypher, params)
            async for record in result:
                rows.append(record.data())
                if len(rows) >= limit:
                    break
        return rows

    async def aclose(self) -> None:
        await self._driver.close()


class Neo4jGraphPort:
    """Execute read-only parameterized Cypher against Neo4j."""

    def __init__(self, transport: Neo4jGraphTransport) -> None:
        self._transport = transport

    async def query(self, command: GraphQueryCommand) -> GraphQueryResult:
        assert_read_only_cypher(command.cypher)
        assert_params_cover_refs(command.cypher, command.params)
        params = dict(command.params)
        params.setdefault("user_id", command.user_id)

        raw_rows = await self._transport.run_query(
            cypher=command.cypher,
            params=params,
            limit=command.limit,
        )
        rows = tuple(
            GraphQueryRow(values={key: _serialize_graph_value(value) for key, value in row.items()})
            for row in raw_rows[: command.limit]
        )
        return GraphQueryResult(rows=rows, row_count=len(rows))

    async def aclose(self) -> None:
        await self._transport.aclose()


def _serialize_graph_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return json.dumps(value, ensure_ascii=False, default=str)
