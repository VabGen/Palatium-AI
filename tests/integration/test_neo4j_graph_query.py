"""Integration tests for Neo4j graph_query (opt-in when Neo4j is reachable)."""

from __future__ import annotations

import json

import pytest

from palatium_ai.domain.graph.types import GraphQueryCommand
from palatium_ai.infrastructure.graph.neo4j_graph_port import Neo4jDriverTransport, Neo4jGraphPort


@pytest.mark.integration
@pytest.mark.asyncio
async def test_neo4j_graph_query_returns_rows(requires_neo4j: tuple[str, str, str]) -> None:
    uri, user, password = requires_neo4j
    transport = Neo4jDriverTransport(uri=uri, user=user, password=password)
    port = Neo4jGraphPort(transport)
    try:
        result = await port.query(
            GraphQueryCommand(
                user_id="integration-user",
                cypher="RETURN $user_id AS user_id, $label AS label LIMIT $lim",
                params={"user_id": "integration-user", "label": "palatium-graph-smoke", "lim": 1},
                limit=1,
            )
        )
    finally:
        await port.aclose()

    assert result.row_count == 1
    assert result.rows[0].values["user_id"] == "integration-user"
    assert result.rows[0].values["label"] == "palatium-graph-smoke"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_platform_graph_query_via_handler(requires_neo4j: tuple[str, str, str]) -> None:
    uri, user, password = requires_neo4j
    from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
    from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler

    transport = Neo4jDriverTransport(uri=uri, user=user, password=password)
    port = Neo4jGraphPort(transport)
    handler = PlatformToolHandler(knowledge_port=InMemoryKnowledgePort(), graph_port=port)
    try:
        result = await handler.call_tool(
            "graph_query",
            {
                "user_id": "integration-user",
                "cypher": "RETURN $user_id AS user_id LIMIT $lim",
                "params_json": json.dumps({"user_id": "integration-user", "lim": 1}),
            },
        )
    finally:
        await port.aclose()

    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["row_count"] == 1
    assert payload["rows"][0]["user_id"] == "integration-user"
