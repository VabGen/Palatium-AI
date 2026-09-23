# mcp_servers/mcp_stub_runtime.py

"""Shared FastMCP HTTP app factory for local MCP stubs (Streamable HTTP)."""

from __future__ import annotations

import os

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from fastmcp import FastMCP
from fastmcp.server.auth import AuthProvider, MultiAuth
from fastmcp.server.auth.providers.jwt import JWTVerifier, StaticTokenVerifier
from fastmcp.tools.function_tool import FunctionTool
from mcp.types import ToolAnnotations
from mcp_stub_auth import anon_mcp_allowed, configured_mcp_token
from starlette.responses import JSONResponse

if TYPE_CHECKING:
    from fastmcp.server.auth.auth import TokenVerifier
    from starlette.requests import Request
    from starlette.types import ASGIApp

_DEFAULT_ISSUER = "palatium-mcp"


def _configured_jwt_secret() -> str | None:
    for key in ("MCP_JWT_SECRET", "JWT_SECRET"):
        raw = os.environ.get(key, "").strip()
        if raw:
            return raw
    return None


def _jwt_issuer() -> str:
    return os.environ.get("MCP_JWT_ISSUER", _DEFAULT_ISSUER).strip() or _DEFAULT_ISSUER


def build_stub_auth(*, server_name: str) -> AuthProvider | None:
    """JWT (aud=mcp:<server>) + optional legacy static Bearer (MultiAuth).

    - ``MCP_JWT_SECRET`` or ``JWT_SECRET`` → HS256 JWTVerifier with audience ``mcp:<name>``
    - ``MCP_AUTH_TOKEN`` → StaticTokenVerifier (local/legacy)
    - both → MultiAuth (either credential accepted)
    - neither + ``MCP_ALLOW_ANON=1`` → no auth
    - neither otherwise → refuse to start
    """
    verifiers: list[TokenVerifier] = []
    secret = _configured_jwt_secret()
    if secret is not None:
        if len(secret) < 32:
            raise RuntimeError("MCP_JWT_SECRET/JWT_SECRET must be at least 32 characters")
        verifiers.append(
            JWTVerifier(
                public_key=secret,
                issuer=_jwt_issuer(),
                audience=f"mcp:{server_name}",
                algorithm="HS256",
            )
        )
    static = configured_mcp_token()
    if static is not None:
        verifiers.append(
            StaticTokenVerifier(
                tokens={static: {"client_id": "palatium-mcp-static", "scopes": ["mcp"]}},
            )
        )
    if not verifiers:
        if anon_mcp_allowed():
            return None
        raise RuntimeError(
            "MCP_JWT_SECRET (or JWT_SECRET) or MCP_AUTH_TOKEN required (set MCP_ALLOW_ANON=1 only for local bootstrap)",
        )
    if len(verifiers) == 1:
        return verifiers[0]
    return MultiAuth(verifiers=verifiers)


def create_stub_mcp(*, name: str, instructions: str) -> FastMCP[Any]:
    """Create a FastMCP server with mask_error_details + stub auth policy."""
    return FastMCP(
        name=name,
        instructions=instructions,
        auth=build_stub_auth(server_name=name),
        mask_error_details=True,
    )


def register_pinned_tool(
    mcp: FastMCP[Any],
    *,
    fn: Any,
    name: str,
    description: str,
    input_schema: Mapping[str, object],
    read_only: bool,
    destructive: bool = False,
) -> None:
    """Register a tool with an exact platform-pinned inputSchema (fingerprint-stable)."""
    schema = {key: value for key, value in input_schema.items() if key != "$schema"}
    tool = FunctionTool.from_function(
        fn,
        name=name,
        description=description,
        annotations=ToolAnnotations(
            read_only_hint=read_only,
            destructive_hint=destructive,
        ),
    )
    mcp.add_tool(tool.model_copy(update={"parameters": dict(schema)}))


def mount_health(mcp: FastMCP[Any], *, server: str) -> None:
    """Unauthenticated liveness probe at ``GET /health``."""

    @mcp.custom_route("/health", methods=["GET"])
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok", "server": server})


def build_http_app(mcp: FastMCP[Any], *, server: str) -> ASGIApp:
    """ASGI app: MCP at ``/`` (keeps existing MCP_SERVERS URLs) + ``/health``."""
    mount_health(mcp, server=server)
    return mcp.http_app(path="/")
