# mcp_servers/edms/edms_mcp_server.py

"""Minimal MCP-compatible EDMS server stub (not JavaEdms runtime)."""

from __future__ import annotations

import json

from typing import Annotated

from fastapi import Depends, FastAPI
from mcp_stub_auth import require_mcp_bearer
from mcp_stub_tools import tools_list_payload
from pydantic import BaseModel, Field

app = FastAPI(title="edms-mcp-server")

_MAX_QUERY_CHARS = 200
_MAX_HITS = 5


class JsonRpcRequest(BaseModel):
    """JSON-RPC 2.0 request envelope."""

    jsonrpc: str = Field(default="2.0")
    method: str
    params: dict[str, object] | None = None
    id: str | None = None


class JsonRpcError(BaseModel):
    """JSON-RPC 2.0 error envelope."""

    code: int
    message: str
    data: dict[str, object] | None = None


class JsonRpcResponse(BaseModel):
    """JSON-RPC 2.0 response envelope."""

    jsonrpc: str = "2.0"
    result: dict[str, object] | None = None
    error: JsonRpcError | None = None
    id: str | None = None


def _call_arguments(params: dict[str, object] | None) -> dict[str, object]:
    raw = (params or {}).get("arguments", {})
    return raw if isinstance(raw, dict) else {}


def _text_result(payload: dict[str, object]) -> dict[str, object]:
    """MCP content payload: single high-signal JSON text block (token-bounded)."""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": False,
    }


_SEARCH_DOCUMENTS_TOOL: dict[str, object] = {
    "name": "search_documents",
    "description": (
        "Search EDMS documents by a free-text query. "
        "Use for lookup/read of contracts, incoming/outgoing, or archive titles. "
        "Do not use for archive/write. "
        "Returns truncated stub hits: document_id, title, score (max "
        f"{_MAX_HITS}). Never invent ids beyond returned hits."
    ),
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
    "side_effect": "read",
    "riskTier": "low",
    "inputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 1,
                "maxLength": _MAX_QUERY_CHARS,
                "description": f"Non-empty search string (max {_MAX_QUERY_CHARS} chars).",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

_ARCHIVE_DOCUMENT_TOOL: dict[str, object] = {
    "name": "archive_document",
    "description": (
        "Archive one EDMS document by exact document_id (write/destructive stub). "
        "Platform HITL must approve before call. "
        "Use only an id from a prior search_documents hit or an explicit user id; never guess. "
        "Returns {document_id, status} confirmation."
    ),
    "annotations": {"readOnlyHint": False, "destructiveHint": True},
    "side_effect": "write",
    "riskTier": "high",
    "inputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "minLength": 1,
                "maxLength": 128,
                "description": "Exact EDMS document_id to archive (no wildcards).",
            },
        },
        "required": ["document_id"],
        "additionalProperties": False,
    },
}

_TOOLS: tuple[dict[str, object], ...] = (_SEARCH_DOCUMENTS_TOOL, _ARCHIVE_DOCUMENT_TOOL)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe (no auth)."""
    return {"status": "ok", "server": "edms"}


@app.post("/")
async def handle_jsonrpc(
    request: JsonRpcRequest,
    _: Annotated[None, Depends(require_mcp_bearer)],
) -> JsonRpcResponse:
    """JSON-RPC 2.0 entrypoint for MCP tools/list and tools/call."""
    if request.method == "tools/list":
        return JsonRpcResponse(
            id=request.id,
            result={"tools": tools_list_payload(_TOOLS, request.params)},
        )

    if request.method == "tools/call":
        params = request.params or {}
        tool_name = params.get("name")
        arguments = _call_arguments(params if isinstance(params, dict) else None)

        if tool_name == "search_documents":
            query = arguments.get("query")
            if not isinstance(query, str) or not query.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: query is required"),
                )
            q = query.strip()[:_MAX_QUERY_CHARS]
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "search_documents",
                        "query": q,
                        "hits": [
                            {
                                "document_id": "stub-doc-1",
                                "title": f"Match for: {q[:80]}",
                                "score": 0.91,
                            },
                        ][:_MAX_HITS],
                        "truncated": True,
                        "max_hits": _MAX_HITS,
                    },
                ),
            )

        if tool_name == "archive_document":
            document_id = arguments.get("document_id")
            if not isinstance(document_id, str) or not document_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(
                        code=-32602,
                        message="Invalid params: document_id is required",
                    ),
                )
            doc_id = document_id.strip()[:128]
            if "*" in doc_id or "?" in doc_id:
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(
                        code=-32602,
                        message="Invalid params: document_id must be exact (no wildcards)",
                    ),
                )
            return JsonRpcResponse(
                id=request.id,
                result=_text_result(
                    {
                        "stub": True,
                        "tool": "archive_document",
                        "document_id": doc_id,
                        "status": "archived",
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
