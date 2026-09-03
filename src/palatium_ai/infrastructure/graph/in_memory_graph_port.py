# src/palatium_ai/infrastructure/graph/in_memory_graph_port.py

"""In-memory GraphPort for tests / stub path without Neo4j."""

from __future__ import annotations

from palatium_ai.domain.graph.cypher_safety import assert_params_cover_refs, assert_read_only_cypher
from palatium_ai.domain.graph.types import GraphQueryCommand, GraphQueryResult, GraphQueryRow


class InMemoryGraphPort:
    """Deterministic stub graph: echoes bound params as a single row."""

    async def query(self, command: GraphQueryCommand) -> GraphQueryResult:
        assert_read_only_cypher(command.cypher)
        assert_params_cover_refs(command.cypher, command.params)
        # Scope awareness: always require user_id in params when referenced, else inject for audit.
        values = {key: str(value) for key, value in command.params.items()}
        values.setdefault("user_id", command.user_id)
        values["cypher_preview"] = command.cypher[:120]
        row = GraphQueryRow(values=values)
        return GraphQueryResult(rows=(row,), row_count=1)
