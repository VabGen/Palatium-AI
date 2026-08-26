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


def require_mcp_bearer(authorization: str | None = Header(default=None)) -> None:
    """Reject requests when MCP_AUTH_TOKEN is set and Authorization does not match.

    When the env var is unset, stubs stay open for local bootstrap only.
    Set MCP_AUTH_TOKEN (same value as the platform client) before any shared network.
    """
    expected = configured_mcp_token()
    if expected is None:
        return
    if authorization is None or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    provided = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
