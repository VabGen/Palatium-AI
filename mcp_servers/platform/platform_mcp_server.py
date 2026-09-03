# mcp_servers/platform/platform_mcp_server.py

"""Minimal MCP-compatible platform knowledge stub (canonical ingest_document)."""

from __future__ import annotations

import json

from typing import Annotated

from contract import (
    _MAX_DOCUMENT_ID_CHARS,
    _MAX_THREAD_ID_CHARS,
    CONSOLIDATE_MEMORY_INPUT_SCHEMA,
    FORGET_MEMORY_INPUT_SCHEMA,
    GRAPH_QUERY_INPUT_SCHEMA,
    INGEST_DOCUMENT_INPUT_SCHEMA,
    SAVE_MEMORY_INPUT_SCHEMA,
    SEARCH_KNOWLEDGE_INPUT_SCHEMA,
    SEARCH_MEMORY_INPUT_SCHEMA,
    WEB_FALLBACK_INPUT_SCHEMA,
)
from fastapi import Depends, FastAPI
from mcp_stub_auth import require_mcp_bearer
from mcp_stub_tools import tools_list_payload
from pydantic import BaseModel, Field

app = FastAPI(title="platform-mcp-server")


class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    method: str
    params: dict[str, object] | None = None
    id: str | None = None


class JsonRpcError(BaseModel):
    code: int
    message: str
    data: dict[str, object] | None = None


class JsonRpcResponse(BaseModel):
    jsonrpc: str = "2.0"
    result: dict[str, object] | None = None
    error: JsonRpcError | None = None
    id: str | None = None


def _call_arguments(params: dict[str, object] | None) -> dict[str, object]:
    raw = (params or {}).get("arguments", {})
    return raw if isinstance(raw, dict) else {}


def _text_result(payload: dict[str, object]) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": False,
    }


_INGEST_DOCUMENT_TOOL: dict[str, object] = {
    "name": "ingest_document",
    "description": (
        "Persist prepared document chunks into the knowledge index (write). "
        "Platform HITL must approve before call. "
        "chunks_json is a JSON array of {index,text,contextual_prefix}. "
        "Returns {document_ref, chunk_count, status}."
    ),
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "side_effect": "write",
    "riskTier": "high",
    "inputSchema": INGEST_DOCUMENT_INPUT_SCHEMA,
}

_TOOLS: tuple[dict[str, object], ...] = (
    _INGEST_DOCUMENT_TOOL,
    {
        "name": "search_knowledge",
        "description": "Hybrid search over ingested knowledge chunks (read).",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "side_effect": "read",
        "riskTier": "low",
        "inputSchema": SEARCH_KNOWLEDGE_INPUT_SCHEMA,
    },
    {
        "name": "search_memory",
        "description": "Hybrid search over episodic memory entries (read).",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "side_effect": "read",
        "riskTier": "low",
        "inputSchema": SEARCH_MEMORY_INPUT_SCHEMA,
    },
    {
        "name": "save_memory",
        "description": "Upsert episodic memory entry (write; HITL required).",
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "side_effect": "write",
        "riskTier": "medium",
        "inputSchema": SAVE_MEMORY_INPUT_SCHEMA,
    },
    {
        "name": "forget_memory",
        "description": "Delete episodic memory entry by key (write; HITL required).",
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
        "side_effect": "write",
        "riskTier": "medium",
        "inputSchema": FORGET_MEMORY_INPUT_SCHEMA,
    },
    {
        "name": "consolidate_memory",
        "description": "Enqueue sleep-time memory consolidation for a thread (write; HITL required).",
        "annotations": {"readOnlyHint": False, "destructiveHint": False},
        "side_effect": "write",
        "riskTier": "medium",
        "inputSchema": CONSOLIDATE_MEMORY_INPUT_SCHEMA,
    },
    {
        "name": "graph_query",
        "description": "Read-only parameterized Cypher against the knowledge graph ($params only).",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "side_effect": "read",
        "riskTier": "low",
        "inputSchema": GRAPH_QUERY_INPUT_SCHEMA,
    },
    {
        "name": "web_fallback",
        "description": "External web search fallback after local knowledge/memory empty (source=web).",
        "annotations": {"readOnlyHint": True, "destructiveHint": False},
        "side_effect": "read",
        "riskTier": "medium",
        "inputSchema": WEB_FALLBACK_INPUT_SCHEMA,
    },
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "server": "platform"}


@app.post("/")
async def handle_jsonrpc(
    request: JsonRpcRequest,
    _: Annotated[None, Depends(require_mcp_bearer)],
) -> JsonRpcResponse:
    if request.method == "tools/list":
        return JsonRpcResponse(
            id=request.id,
            result={"tools": tools_list_payload(_TOOLS, request.params)},
        )

    if request.method == "tools/call":
        params = request.params or {}
        tool_name = params.get("name")
        arguments = _call_arguments(params if isinstance(params, dict) else None)

        if tool_name == "ingest_document":
            user_id = arguments.get("user_id")
            thread_id = arguments.get("thread_id")
            chunks_json = arguments.get("chunks_json")
            if not isinstance(user_id, str) or not user_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: user_id is required"),
                )
            if not isinstance(thread_id, str) or not thread_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: thread_id is required"),
                )
            if not isinstance(chunks_json, str) or not chunks_json.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: chunks_json is required"),
                )
            try:
                chunks = json.loads(chunks_json)
            except json.JSONDecodeError:
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: chunks_json must be valid JSON"),
                )
            if not isinstance(chunks, list) or not chunks:
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: chunks_json must be a non-empty array"),
                )
            document_id = arguments.get("document_id", "")
            doc_id = document_id.strip()[:_MAX_DOCUMENT_ID_CHARS] if isinstance(document_id, str) else ""
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "ingest_document",
                        "thread_id": thread_id.strip()[:_MAX_THREAD_ID_CHARS],
                        "document_id": doc_id or None,
                        "chunk_count": len(chunks[:256]),
                        "document_ref": doc_id or f"stub-ref-{thread_id.strip()[:32]}",
                        "status": "ingested",
                    },
                ),
            )

        if tool_name == "search_knowledge":
            user_id = arguments.get("user_id")
            query = arguments.get("query")
            if not isinstance(user_id, str) or not user_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: user_id is required"),
                )
            if not isinstance(query, str) or not query.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: query is required"),
                )
            thread_id_raw = arguments.get("thread_id", "")
            thread_id = thread_id_raw.strip()[:_MAX_THREAD_ID_CHARS] if isinstance(thread_id_raw, str) else ""
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "search_knowledge",
                        "query": query.strip()[:500],
                        "thread_id": thread_id or None,
                        "hits": [],
                        "hit_count": 0,
                    },
                ),
            )

        if tool_name == "search_memory":
            user_id = arguments.get("user_id")
            query = arguments.get("query")
            if not isinstance(user_id, str) or not user_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: user_id is required"),
                )
            if not isinstance(query, str) or not query.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: query is required"),
                )
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "search_memory",
                        "query": query.strip()[:500],
                        "hits": [],
                        "hit_count": 0,
                    },
                ),
            )

        if tool_name == "save_memory":
            return JsonRpcResponse(
                id=request.id,
                result=_text_result({"stub": True, "tool": "save_memory", "status": "saved"}),
            )

        if tool_name == "forget_memory":
            return JsonRpcResponse(
                id=request.id,
                result=_text_result({"stub": True, "tool": "forget_memory", "forgotten": True}),
            )

        if tool_name == "consolidate_memory":
            thread_id = arguments.get("thread_id")
            if not isinstance(thread_id, str) or not thread_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: thread_id is required"),
                )
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "consolidate_memory",
                        "thread_id": thread_id.strip()[:_MAX_THREAD_ID_CHARS],
                        "status": "queued",
                    },
                ),
            )

        if tool_name == "graph_query":
            user_id = arguments.get("user_id")
            cypher = arguments.get("cypher")
            if not isinstance(user_id, str) or not user_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: user_id is required"),
                )
            if not isinstance(cypher, str) or not cypher.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: cypher is required"),
                )
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "graph_query",
                        "row_count": 0,
                        "rows": [],
                    },
                ),
            )

        if tool_name == "web_fallback":
            user_id = arguments.get("user_id")
            query = arguments.get("query")
            if not isinstance(user_id, str) or not user_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: user_id is required"),
                )
            if not isinstance(query, str) or not query.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: query is required"),
                )
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "web_fallback",
                        "query": query.strip()[:500],
                        "source": "web",
                        "reliability": "external_unverified",
                        "hits": [],
                        "hit_count": 0,
                    },
                ),
            )

        return JsonRpcResponse(
            id=request.id,
            error=JsonRpcError(code=-32601, message=f"Unknown tool: {tool_name}"),
        )

    return JsonRpcResponse(
        id=request.id,
        error=JsonRpcError(code=-32601, message=f"Method not found: {request.method}"),
    )
