# src/mcp_servers/analytics/analytics_mcp_server.py

"""Минимальный MCP-compatible analytics server stub."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI
from mcp_stub_auth import require_mcp_bearer
from pydantic import BaseModel, Field

app = FastAPI(title="analytics-mcp-server")


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


_GET_SALES_METRICS_TOOL: dict[str, object] = {
    "name": "get_sales_metrics",
    "description": "Return sales KPIs for a date range.",
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
    "side_effect": "read",
    "riskTier": "low",
    "inputSchema": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {
            "period": {
                "type": "string",
                "minLength": 1,
                "description": "Reporting period (e.g. 2025-Q1).",
            },
        },
        "required": ["period"],
        "additionalProperties": False,
    },
}


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe (no auth)."""
    return {"status": "ok", "server": "analytics"}


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
                "tools": [_GET_SALES_METRICS_TOOL],
            },
        )

    if request.method == "tools/call":
        params = request.params or {}
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        if tool_name != "get_sales_metrics":
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=-32601, message=f"Unknown tool: {tool_name}"),
            )

        period = arguments.get("period") if isinstance(arguments, dict) else None
        if not isinstance(period, str) or not period.strip():
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=-32602, message="Invalid params: period is required"),
            )

        return JsonRpcResponse(
            id=request.id,
            result={
                "content": [
                    {
                        "type": "text",
                        "text": (f"Stub analytics for {period}: revenue=1.2M, orders=842, conversion=3.4%"),
                    },
                ],
                "isError": False,
            },
        )

    return JsonRpcResponse(
        id=request.id,
        error=JsonRpcError(code=-32601, message=f"Method not found: {request.method}"),
    )
