# mcp_servers/gateway/gateway_mcp_server.py

"""MCP gateway: ProxyProvider → upstream + pin allowlist (Phase 6 scaffold).

Does **not** invent EDMS/analytics business APIs (090). Point
``MCP_UPSTREAM_URL`` at today's FastMCP stub or a future real adapter that
already speaks MCP with Host-pinned tool names/schemas.

Platform is never proxied — Host ``PlatformToolHandler`` only.

Env (uvicorn):
  MCP_GATEWAY_SERVER=edms|analytics
  MCP_UPSTREAM_URL=http://127.0.0.1:8080
  MCP_UPSTREAM_BEARER= optional Bearer for upstream
  MCP_JWT_* / MCP_AUTH_TOKEN — same Host-facing auth as stubs (aud=mcp:<server>)
"""

from __future__ import annotations

import os

from typing import Any

from fastmcp.server.providers.proxy import FastMCPProxy, ProxyClient
from mcp_stub_runtime import build_stub_auth, mount_health
from pin_allowlist import allowlist_for
from pin_filter import PinAllowlistMiddleware


def _upstream_client(upstream_url: str) -> ProxyClient[Any]:
    bearer = os.environ.get("MCP_UPSTREAM_BEARER", "").strip()
    if bearer:
        return ProxyClient(upstream_url, auth=bearer)
    return ProxyClient(upstream_url)


def build_gateway(*, server_name: str, upstream_url: str) -> FastMCPProxy:
    """Build Host-facing FastMCP proxy with pin-name filter."""
    if server_name not in {"edms", "analytics"}:
        raise ValueError(f"MCP gateway does not proxy {server_name!r} (platform is Host-local only; never proxied)")
    if not upstream_url.strip():
        raise ValueError("upstream_url is required")
    allowed = allowlist_for(server_name)
    proxy = FastMCPProxy(
        client_factory=lambda: _upstream_client(upstream_url),
        name=server_name,
        instructions=(
            f"Palatium MCP gateway for {server_name}. "
            "Only platform-pinned tool names are exposed; "
            "Host ToolPolicy fingerprints remain the execution gate. "
            "Not a substitute for a real EDMS adapter contract."
        ),
        auth=build_stub_auth(server_name=server_name),
        mask_error_details=True,
        provider_error_strategy="raise",
        identity="proxy",
    )
    proxy.add_middleware(PinAllowlistMiddleware(allowed))
    mount_health(proxy, server=f"gateway:{server_name}")
    return proxy


def build_app_from_env() -> object:
    """ASGI app for uvicorn — requires MCP_GATEWAY_SERVER + MCP_UPSTREAM_URL."""
    server = os.environ.get("MCP_GATEWAY_SERVER", "").strip()
    upstream = os.environ.get("MCP_UPSTREAM_URL", "").strip()
    if server not in {"edms", "analytics"}:
        raise RuntimeError(
            "MCP_GATEWAY_SERVER must be 'edms' or 'analytics' (platform is Host-local only; never proxied)"
        )
    if not upstream:
        raise RuntimeError("MCP_UPSTREAM_URL is required (stub URL today; real MCP adapter later)")
    return build_gateway(server_name=server, upstream_url=upstream).http_app(path="/")


# Uvicorn target: ``gateway_mcp_server:app``
app = build_app_from_env() if os.environ.get("MCP_GATEWAY_SERVER", "").strip() else None
