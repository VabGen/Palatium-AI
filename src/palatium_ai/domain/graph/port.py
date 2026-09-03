# src/palatium_ai/domain/graph/port.py

"""GraphPort — parameterized Neo4j read queries (070 ``graph_query``)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.graph.types import GraphQueryCommand, GraphQueryResult


class GraphPort(Protocol):
    """Execute read-only Cypher with ``$param`` bindings."""

    async def query(self, command: GraphQueryCommand) -> GraphQueryResult:
        """Run parameterized Cypher; implementations must reject write clauses."""
