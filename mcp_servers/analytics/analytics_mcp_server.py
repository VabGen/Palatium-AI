# mcp_servers/analytics/analytics_mcp_server.py

"""Analytics MCP stub on FastMCP Streamable HTTP."""

from __future__ import annotations

from mcp_servers.mcp_stub_runtime import build_http_app, create_stub_mcp, register_pinned_tool
from palatium_ai.domain.mcp.external_schemas import (
    ANALYTICS_PERIOD_MAX_CHARS,
    ANALYTICS_SALES_METRICS_SCHEMA,
)

_MAX_PERIOD_CHARS = ANALYTICS_PERIOD_MAX_CHARS

mcp = create_stub_mcp(
    name="analytics",
    instructions="Analytics stub: get_sales_metrics (read-only KPIs for one reporting period).",
)


def get_sales_metrics(period: str) -> dict[str, object]:
    """Return sales KPIs for one reporting period."""
    period_label = period.strip()[:_MAX_PERIOD_CHARS]
    if not period_label:
        raise ValueError("period is required")
    if "*" in period_label or "?" in period_label:
        raise ValueError("period must be exact (no wildcards)")
    return {
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
    }


register_pinned_tool(
    mcp,
    fn=get_sales_metrics,
    name="get_sales_metrics",
    description=(
        "Return sales KPIs for one reporting period. "
        "Use for revenue/orders/conversion summaries; not for EDMS documents or writes. "
        "Period must be an exact label (e.g. 2025-Q1), no wildcards. "
        "Returns truncated stub metrics: revenue, orders, conversion_pct."
    ),
    input_schema=ANALYTICS_SALES_METRICS_SCHEMA,
    read_only=True,
)

app = build_http_app(mcp, server="analytics")
