# src/palatium_ai/infrastructure/mcp/graph_web_tool_ops.py

"""In-process ``graph_query`` / ``web_fallback`` MCP ops (070)."""

from __future__ import annotations

import json

from typing import TYPE_CHECKING

from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.graph.cypher_safety import assert_params_cover_refs, assert_read_only_cypher
from palatium_ai.domain.graph.types import GraphQueryCommand
from palatium_ai.domain.mcp.models import MCPToolResult
from palatium_ai.domain.web.types import WebSearchQuery

if TYPE_CHECKING:
    from palatium_ai.domain.graph.port import GraphPort
    from palatium_ai.domain.web.port import WebSearchPort


async def graph_query(graph_port: GraphPort | None, arguments: dict[str, object]) -> MCPToolResult:
    if graph_port is None:
        return _error_result("graph_query unavailable: graph port not configured")
    user_id = arguments.get("user_id")
    cypher = arguments.get("cypher")
    params_json = arguments.get("params_json", "{}")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    if not isinstance(cypher, str) or not cypher.strip():
        return _error_result("Invalid params: cypher is required")
    if not isinstance(params_json, str):
        return _error_result("Invalid params: params_json must be a JSON object string")

    try:
        raw_params = json.loads(params_json) if params_json.strip() else {}
    except json.JSONDecodeError:
        return _error_result("Invalid params: params_json must be valid JSON")
    if not isinstance(raw_params, dict):
        return _error_result("Invalid params: params_json must be a JSON object")

    limit_raw = arguments.get("limit", "25")
    try:
        limit = max(1, min(int(str(limit_raw).strip()), 100))
    except ValueError:
        return _error_result("Invalid params: limit must be an integer between 1 and 100")

    params = {str(key): value for key, value in raw_params.items()}
    # Always overwrite tenant scope — client params_json must not win.
    params["user_id"] = user_id.strip()

    try:
        assert_read_only_cypher(cypher)
        assert_params_cover_refs(cypher, params)
        result = await graph_port.query(
            GraphQueryCommand(
                user_id=user_id.strip(),
                cypher=cypher.strip(),
                params=params,
                limit=limit,
            )
        )
    except ValueError as exc:
        return _error_result(f"Invalid params: {exc}")

    payload = {
        "tool": "graph_query",
        "row_count": result.row_count,
        "rows": [dict(row.values) for row in result.rows[:limit]],
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def web_fallback(
    web_search_port: WebSearchPort | None,
    arguments: dict[str, object],
) -> MCPToolResult:
    """External web search fallback — results always tagged as ``source=web`` (070)."""
    if web_search_port is None:
        return _error_result("web_fallback unavailable: web search port not configured")
    user_id = arguments.get("user_id")
    query = arguments.get("query")
    if not isinstance(user_id, str) or not user_id.strip():
        return _error_result("Invalid params: user_id is required")
    if not isinstance(query, str) or not query.strip():
        return _error_result("Invalid params: query is required")

    limit_raw = arguments.get("max_results", "5")
    try:
        max_results = max(1, min(int(str(limit_raw).strip()), 10))
    except ValueError:
        return _error_result("Invalid params: max_results must be an integer between 1 and 10")

    await _audit_web_fallback(user_id=user_id.strip(), query_len=len(query.strip()))

    result = await web_search_port.search(
        WebSearchQuery(
            user_id=user_id.strip(),
            query=query.strip()[:500],
            max_results=max_results,
        )
    )
    payload = {
        "tool": "web_fallback",
        "query": query.strip()[:500],
        "source": "web",
        "reliability": "external_unverified",
        "provider": result.provider,
        "hits": [
            {
                "title": hit.title,
                "url": hit.url,
                "snippet": hit.snippet,
                "score": hit.score,
                "source": "web",
            }
            for hit in result.hits
        ],
        "hit_count": result.hit_count,
        "max_results": max_results,
        "note": result.note,
    }
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        is_error=False,
    )


async def _audit_web_fallback(*, user_id: str, query_len: int) -> None:
    from datetime import UTC, datetime

    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await get_audit_logger().append_async(
        timestamp=timestamp,
        conversation_id=f"web_fallback:{user_id}",
        event="web_fallback_invoked",
        metadata={"user_id": user_id, "query_len": str(query_len)},
    )


def _error_result(message: str) -> MCPToolResult:
    return MCPToolResult(
        content=[{"type": "text", "text": json.dumps({"error": message}, ensure_ascii=False)}],
        is_error=True,
    )
