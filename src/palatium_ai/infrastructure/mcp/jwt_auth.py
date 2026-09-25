# src/palatium_ai/infrastructure/mcp/jwt_auth.py

"""Mint short-lived HS* JWTs for Host → MCP calls (aud=mcp:<server>)."""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import jwt

from palatium_ai.domain.mcp.auth_policy import (
    DEFAULT_MCP_JWT_ALGORITHM,
    DEFAULT_MCP_JWT_ISSUER,
    DEFAULT_MCP_JWT_TTL_SECONDS,
    mcp_audience,
)

if TYPE_CHECKING:
    from palatium_ai.core.config.mcp import MCPConfig
    from palatium_ai.core.config.settings import Settings


def issue_mcp_access_token(
    *,
    server_name: str,
    signing_secret: str,
    issuer: str = DEFAULT_MCP_JWT_ISSUER,
    ttl_seconds: int = DEFAULT_MCP_JWT_TTL_SECONDS,
    subject: str = "palatium-host",
    algorithm: str = DEFAULT_MCP_JWT_ALGORITHM,
) -> str:
    """Create a bearer JWT bound to one MCP server audience."""
    secret = signing_secret.strip()
    if len(secret) < 32:
        raise ValueError("MCP JWT signing secret must be at least 32 characters")
    if not algorithm.startswith("HS"):
        raise ValueError("MCP JWT minting supports HS* only in Phase 3")
    now = int(time.time())
    ttl = max(60, min(int(ttl_seconds), 3600))
    payload = {
        "sub": subject,
        "iss": issuer,
        "aud": mcp_audience(server_name),
        "iat": now,
        "exp": now + ttl,
        "client_id": subject,
    }
    return jwt.encode(payload, secret, algorithm=algorithm)


def resolve_mcp_bearer(
    mcp: MCPConfig,
    server_name: str,
    *,
    signing_secret: str | None,
) -> str | None:
    """Prefer per-server JWT when a signing secret is configured; else static token.

    Order:
    1. Per-server static override (``MCP_SERVER_AUTH_TOKENS``) — emergency / legacy
    2. Mint ``aud=mcp:<server>`` JWT when ``signing_secret`` is set
    3. Shared static ``MCP_AUTH_TOKEN``
    """
    override = mcp.server_auth_tokens.get(server_name)
    if override is not None:
        text = override.get_secret_value().strip()
        if text:
            return text
    if signing_secret and signing_secret.strip():
        return issue_mcp_access_token(
            server_name=server_name,
            signing_secret=signing_secret,
            issuer=mcp.jwt_issuer,
            ttl_seconds=mcp.jwt_ttl_seconds,
            algorithm=mcp.jwt_algorithm,
        )
    if mcp.auth_token is None:
        return None
    return mcp.auth_token.get_secret_value()


def resolve_settings_bearer(settings: Settings, server_name: str) -> str | None:
    """Resolve the Host→MCP bearer straight from ``Settings`` (infrastructure-side).

    Lives here — not on ``Settings`` — so ``core/`` never imports ``infrastructure/``
    (rule 000 layer contract, enforced by ``scripts/check_import_layers.py``).
    """
    resolver = getattr(settings, "mcp_jwt_signing_secret", None)
    signing_secret = resolver() if callable(resolver) else None
    return resolve_mcp_bearer(settings.mcp, server_name, signing_secret=signing_secret)
