# src/palatium_ai/infrastructure/graph/in_memory_graph_port.py

"""In-memory GraphPort for tests / stub path without Neo4j."""

from __future__ import annotations

from palatium_ai.domain.graph.cypher_safety import TENANT_SCOPE_PARAM, assert_graph_query_safe
from palatium_ai.domain.graph.types import GraphQueryCommand, GraphQueryResult, GraphQueryRow


class InMemoryGraphPort:
    """Deterministic stub graph: echoes bound params as a single row."""

    async def query(self, command: GraphQueryCommand) -> GraphQueryResult:
        params = dict(command.params)
        # Force tenant scope: client-supplied params must never win over the authenticated user (020/070).
        params[TENANT_SCOPE_PARAM] = command.user_id
        assert_graph_query_safe(command.cypher, params)
        # Echo the forced tenant scope so audit/debug rows cannot report a foreign user_id.
        values = {key: str(value) for key, value in params.items()}
        values["cypher_preview"] = command.cypher[:120]
        row = GraphQueryRow(values=values)
        return GraphQueryResult(rows=(row,), row_count=1)
