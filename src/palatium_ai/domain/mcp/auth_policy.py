# src/palatium_ai/domain/mcp/auth_policy.py

"""MCP bearer audience / issuer conventions (Host ↔ MCP resource servers)."""

from __future__ import annotations

DEFAULT_MCP_JWT_ISSUER = "palatium-mcp"
DEFAULT_MCP_JWT_TTL_SECONDS = 300
DEFAULT_MCP_JWT_ALGORITHM = "HS256"


def mcp_audience(server_name: str) -> str:
    """Canonical JWT ``aud`` for one MCP server: ``mcp:<server>``."""
    name = server_name.strip()
    if not name:
        raise ValueError("MCP server name is empty")
    return f"mcp:{name}"
