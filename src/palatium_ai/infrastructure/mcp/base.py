# src/palatium_ai/infrastructure/mcp/base.py

"""FastMCP HTTP client for MCP servers (Streamable HTTP, protocol auto-negotiate)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, TypeVar

import httpx
import structlog

from jsonschema import Draft202012Validator
from tenacity import (
    AsyncRetrying,
    retry_if_exception,
    stop_after_attempt,
    wait_fixed,
)

from palatium_ai.domain.mcp.models import (
    JsonRpcError,
    MCPToolCall,
    MCPToolDescriptor,
    MCPToolResult,
    MCPToolSummary,
)

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings

T = TypeVar("T")

logger = structlog.get_logger(__name__)


def _normalize_server_url(url: str) -> str:
    """FastMCP Client expects a trailing slash when MCP is mounted at ``/``."""
    stripped = url.strip()
    if not stripped:
        return stripped
    return stripped if stripped.endswith("/") else f"{stripped}/"


def _is_transient_mcp_error(exc: BaseException) -> bool:
    """Retry transport failures and upstream 5xx; never retry auth/client errors."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


def _tool_to_descriptor(tool: Any) -> MCPToolDescriptor:
    """Map FastMCP / MCP SDK tool object to platform MCPToolDescriptor.

    Strips server risk attestation (annotations / sideEffect / riskTier) — Host
    ToolPolicy pins are the only authority (Phase 5 control plane).
    """
    if hasattr(tool, "model_dump"):
        raw = tool.model_dump(by_alias=True, exclude_none=True)
    elif isinstance(tool, dict):
        raw = dict(tool)
    else:
        raw = {
            "name": getattr(tool, "name", ""),
            "description": getattr(tool, "description", "") or "",
            "inputSchema": getattr(tool, "inputSchema", None)
            or getattr(tool, "input_schema", None)
            or getattr(tool, "parameters", {})
            or {},
        }
    # Client model_dump uses input_schema; AliasChoices accept both.
    if "inputSchema" not in raw and "input_schema" in raw:
        raw = {**raw, "inputSchema": raw["input_schema"]}
    if "parameters" in raw and not raw.get("inputSchema") and not raw.get("input_schema"):
        raw = {**raw, "inputSchema": raw["parameters"]}
    for untrusted in ("annotations", "side_effect", "sideEffect", "risk_tier", "riskTier"):
        raw.pop(untrusted, None)
    return MCPToolDescriptor.model_validate(raw)


def _content_to_dicts(content: Any) -> list[dict[str, object]]:
    """Normalize CallToolResult.content to JSON-serializable dict blocks."""
    if not content:
        return []
    out: list[dict[str, object]] = []
    for item in content:
        if hasattr(item, "model_dump"):
            dumped = item.model_dump(exclude_none=True)
            block: dict[str, object] = {
                "type": str(dumped.get("type", "text")),
                "text": str(dumped.get("text", "")),
            }
            out.append(block)
        elif isinstance(item, dict):
            out.append(dict(item))
        else:
            out.append({"type": "text", "text": str(item)})
    return out


class MCPJsonRpcClient:
    """Host→MCP client via ``fastmcp.Client`` (keeps historical class name for tests)."""

    def __init__(
        self,
        server_url: str,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        *,
        server_name: str | None = None,
    ) -> None:
        self._server_url = _normalize_server_url(server_url)
        self._settings = settings
        self._server_name = server_name
        self._http_client = http_client

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Shared HTTP client used by registry health checks (not by FastMCP Client)."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.mcp.timeout_seconds),
            )
        return self._http_client

    def _auth_token(self) -> str | None:
        if self._server_name is not None and hasattr(self._settings, "resolve_mcp_bearer"):
            return self._settings.resolve_mcp_bearer(self._server_name)
        mcp = self._settings.mcp
        if self._server_name is not None:
            if hasattr(mcp, "resolve_static_token"):
                return mcp.resolve_static_token(self._server_name)
            if hasattr(mcp, "resolve_auth_token"):
                return mcp.resolve_auth_token(self._server_name)
        if getattr(mcp, "auth_token", None) is not None:
            token = mcp.auth_token
            if token is None:
                return None
            return token.get_secret_value() if hasattr(token, "get_secret_value") else str(token)
        return None

    def _auth_headers(self) -> dict[str, str]:
        """Bearer headers for health probes (FastMCP Client uses ``auth=`` separately)."""
        token = self._auth_token()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    async def list_tools(self) -> list[MCPToolDescriptor]:
        """tools/list with full schemas."""
        return await self._with_retry(self._list_tools_once)

    async def list_tool_summaries(self) -> list[MCPToolSummary]:
        """Discovery cards: full list then strip schemas locally (progressive disclosure)."""
        tools = await self.list_tools()
        return [tool.to_summary() for tool in tools]

    async def call_tool(self, tool_call: MCPToolCall) -> MCPToolResult:
        """tools/call on the remote MCP server."""

        async def _once() -> MCPToolResult:
            return await self._call_tool_once(tool_call)

        return await self._with_retry(_once)

    @staticmethod
    def validate_arguments(
        descriptor: MCPToolDescriptor,
        arguments: dict[str, object],
    ) -> None:
        """Validate arguments against JSON Schema 2020-12."""
        Draft202012Validator(descriptor.input_schema).validate(arguments)

    async def _with_retry(self, operation: Callable[[], Awaitable[T]]) -> T:
        attempts = max(1, int(self._settings.mcp.retry_attempts))
        delay = max(0.0, float(self._settings.mcp.retry_delay))
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_fixed(delay),
            retry=retry_if_exception(_is_transient_mcp_error),
            reraise=True,
        ):
            with attempt:
                return await operation()
        raise RuntimeError("MCP client retry loop exited without result")

    async def _list_tools_once(self) -> list[MCPToolDescriptor]:
        from fastmcp import Client

        logger.debug("mcp.client.list_tools", server_url=self._server_url)
        try:
            async with Client(
                self._server_url,
                auth=self._auth_token(),
                mode="auto",
            ) as client:
                tools = await client.list_tools()
        except Exception as exc:
            raise _map_client_error(exc) from exc
        return [_tool_to_descriptor(tool) for tool in tools]

    async def _call_tool_once(self, tool_call: MCPToolCall) -> MCPToolResult:
        from fastmcp import Client

        logger.debug(
            "mcp.client.call_tool",
            server_url=self._server_url,
            tool=tool_call.name,
        )
        try:
            async with Client(
                self._server_url,
                auth=self._auth_token(),
                mode="auto",
            ) as client:
                result = await client.call_tool(tool_call.name, tool_call.arguments)
        except Exception as exc:
            raise _map_client_error(exc) from exc
        return MCPToolResult(
            content=_content_to_dicts(getattr(result, "content", None)),
            is_error=bool(getattr(result, "is_error", False)),
        )

    async def close(self) -> None:
        """Close the shared health-check HTTP client when owned locally."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


def _map_client_error(exc: BaseException) -> BaseException:
    """Preserve httpx errors; wrap protocol errors as MCPJsonRpcError."""
    if isinstance(exc, (httpx.HTTPError, MCPJsonRpcError)):
        return exc
    message = str(exc) or type(exc).__name__
    return MCPJsonRpcError(JsonRpcError(code=-32000, message=message[:500]))


class MCPJsonRpcError(RuntimeError):
    """Protocol / tool error from an MCP server (historical name)."""

    def __init__(self, error: JsonRpcError) -> None:
        self.error = error
        super().__init__(f"MCP JSON-RPC error {error.code}: {error.message}")
