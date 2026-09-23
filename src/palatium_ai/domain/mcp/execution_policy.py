# src/palatium_ai/domain/mcp/execution_policy.py

"""Which MCP servers are Host-local capabilities (never remote HTTP for execute)."""

from __future__ import annotations

# Canonical 070 tools mutate knowledge/memory/graph through Host ports.
# Discovery = static pins; execute = PlatformToolHandler. Never via MCP_SERVERS URL.
LOCAL_EXECUTION_SERVERS: frozenset[str] = frozenset({"platform"})


def requires_local_handler(server_name: str) -> bool:
    """True when ``call_tool`` must use a registered local handler, not HTTP."""
    return server_name.strip() in LOCAL_EXECUTION_SERVERS


def has_local_capability(server_name: str) -> bool:
    """True when the server is a Host-local capability (URL not required)."""
    return requires_local_handler(server_name)
