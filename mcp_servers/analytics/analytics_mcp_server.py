# mcp_servers/analytics/analytics_mcp_server.py

"""Minimal MCP-compatible analytics server stub."""

from __future__ import annotations

import json

from typing import Annotated

from contract import _MAX_PERIOD_CHARS, SALES_METRICS_INPUT_SCHEMA
from fastapi import Depends, FastAPI
from mcp_stub_auth import require_mcp_bearer
from mcp_stub_tools import tools_list_payload
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


def _call_arguments(params: dict[str, object] | None) -> dict[str, object]:
    raw = (params or {}).get("arguments", {})
    return raw if isinstance(raw, dict) else {}


def _text_result(payload: dict[str, object]) -> dict[str, object]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": False,
    }


_GET_SALES_METRICS_TOOL: dict[str, object] = {
    "name": "get_sales_metrics",
    "description": (
        "Return sales KPIs for one reporting period. "
        "Use for revenue/orders/conversion summaries; not for EDMS documents or writes. "
        "Period must be an exact label (e.g. 2025-Q1), no wildcards. "
        "Returns truncated stub metrics: revenue, orders, conversion_pct."
    ),
    "annotations": {"readOnlyHint": True, "destructiveHint": False},
    "side_effect": "read",
    "riskTier": "low",
    "inputSchema": SALES_METRICS_INPUT_SCHEMA,
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
            result={"tools": tools_list_payload((_GET_SALES_METRICS_TOOL,), request.params)},
        )

    if request.method == "tools/call":
        params = request.params or {}
        tool_name = params.get("name")
        arguments = _call_arguments(params if isinstance(params, dict) else None)

        if tool_name != "get_sales_metrics":
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=-32601, message=f"Unknown tool: {tool_name}"),
            )

        period = arguments.get("period")
        if not isinstance(period, str) or not period.strip():
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(code=-32602, message="Invalid params: period is required"),
            )
        period_label = period.strip()[:_MAX_PERIOD_CHARS]
        if "*" in period_label or "?" in period_label:
            return JsonRpcResponse(
                id=request.id,
                error=JsonRpcError(
                    code=-32602,
                    message="Invalid params: period must be exact (no wildcards)",
                ),
            )

        return JsonRpcResponse(
            id=request.id,
            result=_text_result(
                {
                    "stub": True,
                    "tool": "get_sales_metrics",
                    "period": period_label,
                    "metrics": {
                        "revenue": 1_200_000,
                        "orders": 842,
                        "conversion_pct": 3.4,
                    },
                    "currency": "USD",
                    "truncated": True,
                },
            ),
        )

    return JsonRpcResponse(
        id=request.id,
        error=JsonRpcError(code=-32601, message=f"Method not found: {request.method}"),
    )
