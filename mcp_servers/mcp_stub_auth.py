# mcp_servers/mcp_stub_auth.py

"""Shared Bearer auth for local MCP JSON-RPC stubs."""

from __future__ import annotations

import os
import secrets

from fastapi import Header, HTTPException, status


def configured_mcp_token() -> str | None:
    """Return MCP_AUTH_TOKEN when set (empty string → None)."""
    raw = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    return raw or None


def anon_mcp_allowed() -> bool:
    """Explicit local-only opt-in when MCP_AUTH_TOKEN is unset (default: deny)."""
    raw = os.environ.get("MCP_ALLOW_ANON", "").strip().lower()
    return raw in {"1", "true", "yes"}


def require_mcp_bearer(authorization: str | None = Header(default=None)) -> None:
    """Require a matching Bearer token for stub JSON-RPC.

    Fail-closed: missing MCP_AUTH_TOKEN rejects all callers unless MCP_ALLOW_ANON
    is explicitly set (local bootstrap only). Empty Bearer / whitespace-only
    tokens are always rejected when a token is configured.
    """
    expected = configured_mcp_token()
    if expected is None:
        if anon_mcp_allowed():
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="MCP_AUTH_TOKEN required (set MCP_ALLOW_ANON=1 only for local bootstrap)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = authorization.removeprefix("Bearer ").strip()
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
