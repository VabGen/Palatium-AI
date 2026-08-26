# src/mcp_servers/edms/edms_mcp_server.py

"""Минимальный MCP-compatible EDMS server stub."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from mcp_stub_auth import require_mcp_bearer
from pydantic import BaseModel, Field

app = FastAPI(title="edms-mcp-server")


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


_SEARCH_DOCUMENTS_TOOL: dict[str, object] = {
    "name": "search_documents",
    "description": "Search EDMS documents by query string.",
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
                "description": "Search string for EDMS documents.",
            },
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

_ARCHIVE_DOCUMENT_TOOL: dict[str, object] = {
    "name": "archive_document",
    "description": "Archive an EDMS document by id (write side-effect; requires HITL).",
    "annotations": {"readOnlyHint": False, "destructiveHint": False},
    "side_effect": "write",
    "riskTier": "high",
    "inputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "document_id": {
                "type": "string",
                "minLength": 1,
                "description": "EDMS document identifier to archive.",
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
            result={
                "tools": list(_TOOLS),
            },
        )

    if request.method == "tools/call":
        params = request.params or {}
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name == "search_documents":
            query = arguments.get("query") if isinstance(arguments, dict) else None
            if not isinstance(query, str) or not query.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: query is required"),
                )
            return JsonRpcResponse(
                id=request.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": f"Stub EDMS result for query: {query}",
                        },
                    ],
                    "isError": False,
                },
            )

        if tool_name == "archive_document":
            document_id = arguments.get("document_id") if isinstance(arguments, dict) else None
            if not isinstance(document_id, str) or not document_id.strip():
                return JsonRpcResponse(
                    id=request.id,
                    error=JsonRpcError(code=-32602, message="Invalid params: document_id is required"),
                )
            return JsonRpcResponse(
                id=request.id,
                result={
                    "content": [
                        {
                            "type": "text",
                            "text": f"Stub EDMS archived document_id={document_id.strip()}",
                        },
                    ],
                    "isError": False,
                },
            )

        return JsonRpcResponse(
            id=request.id,
            error=JsonRpcError(code=-32601, message=f"Unknown tool: {tool_name}"),
        )

    return JsonRpcResponse(
        id=request.id,
        error=JsonRpcError(code=-32601, message=f"Method not found: {request.method}"),
    )
