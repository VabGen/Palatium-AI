# mcp_servers/gateway/pin_allowlist.py

"""Pin allowlist for MCP gateway (must match Host PlatformToolPin names).

Platform is never proxied — Host executes via in-process PlatformToolHandler.
Real EDMS/analytics adapters plug in as ``MCP_UPSTREAM_URL`` later (090: no
invented Канцлер contracts here).
"""

from __future__ import annotations

# Keep in sync with domain PlatformToolPin keys (tests/unit/test_mcp_gateway.py).
GATEWAY_PINNED_TOOLS: dict[str, frozenset[str]] = {
    "edms": frozenset({"search_documents", "archive_document"}),
    "analytics": frozenset({"get_sales_metrics"}),
}

GATEWAY_SERVERS: frozenset[str] = frozenset(GATEWAY_PINNED_TOOLS)


def allowlist_for(server_name: str) -> frozenset[str]:
    """Return pinned tool names for a gateway server or raise."""
    try:
        return GATEWAY_PINNED_TOOLS[server_name]
    except KeyError as exc:
        raise ValueError(
            f"MCP gateway does not proxy server {server_name!r}; allowed: {sorted(GATEWAY_SERVERS)}"
        ) from exc
