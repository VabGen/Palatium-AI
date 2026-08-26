# src/palatium_ai/infrastructure/mcp/base.py

"""JSON-RPC 2.0 client for MCP servers with JSON Schema validation."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

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
    JsonRpcRequest,
    JsonRpcResponse,
    MCPToolCall,
    MCPToolDescriptor,
    MCPToolResult,
)

if TYPE_CHECKING:
    from palatium_ai.core.config.settings import Settings

logger = structlog.get_logger(__name__)


def _is_transient_mcp_http_error(exc: BaseException) -> bool:
    """Retry transport failures and upstream 5xx; never retry auth/client errors."""
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return False


class MCPJsonRpcClient:
    """Клиент JSON-RPC 2.0 для MCP server."""

    def __init__(
        self,
        server_url: str,
        settings: Settings,
        http_client: httpx.AsyncClient | None = None,
        *,
        server_name: str | None = None,
    ) -> None:
        self._server_url = server_url
        self._settings = settings
        self._server_name = server_name
        self._http_client = http_client

    @property
    def http_client(self) -> httpx.AsyncClient:
        """Возвращает HTTP клиент."""
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._settings.mcp.timeout_seconds),
            )
        return self._http_client

    def _auth_headers(self) -> dict[str, str]:
        token: str | None = None
        if self._server_name is not None:
            token = self._settings.mcp.resolve_auth_token(self._server_name)
        elif self._settings.mcp.auth_token is not None:
            token = self._settings.mcp.auth_token.get_secret_value()
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    async def list_tools(self) -> list[MCPToolDescriptor]:
        """Получает tools/list у MCP server."""
        response = await self._send_request("tools/list", {})
        raw_result = response.result
        if not isinstance(raw_result, dict):
            return []

        raw_tools = raw_result.get("tools", [])
        if not isinstance(raw_tools, list):
            return []
        return [MCPToolDescriptor.model_validate(tool) for tool in raw_tools]

    async def call_tool(self, tool_call: MCPToolCall) -> MCPToolResult:
        """Вызывает tools/call на MCP server."""
        response = await self._send_request(
            "tools/call",
            {
                "name": tool_call.name,
                "arguments": tool_call.arguments,
            },
        )
        raw_result = response.result
        if not isinstance(raw_result, dict):
            return MCPToolResult(content=[], isError=True)
        return MCPToolResult.model_validate(raw_result)

    @staticmethod
    def validate_arguments(
        descriptor: MCPToolDescriptor,
        arguments: dict[str, object],
    ) -> None:
        """Валидирует аргументы по JSON Schema 2020-12."""
        Draft202012Validator(descriptor.input_schema).validate(arguments)

    async def _send_request(
        self,
        method: str,
        params: dict[str, object] | None,
    ) -> JsonRpcResponse:
        """Отправляет JSON-RPC 2.0 request и валидирует envelope ответа."""
        attempts = max(1, int(self._settings.mcp.retry_attempts))
        delay = max(0.0, float(self._settings.mcp.retry_delay))
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(attempts),
            wait=wait_fixed(delay),
            retry=retry_if_exception(_is_transient_mcp_http_error),
            reraise=True,
        ):
            with attempt:
                return await self._post_jsonrpc(method=method, params=params)
        raise RuntimeError("MCP JSON-RPC retry loop exited without result")

    async def _post_jsonrpc(
        self,
        *,
        method: str,
        params: dict[str, object] | None,
    ) -> JsonRpcResponse:
        request = JsonRpcRequest(
            method=method,
            params=params,
            id=str(uuid4()),
        )
        logger.debug("mcp.jsonrpc.request", method=method, server_url=self._server_url)
        http_response = await self.http_client.post(
            self._server_url,
            json=request.model_dump(mode="json", by_alias=True),
            headers=self._auth_headers(),
        )
        http_response.raise_for_status()
        response = JsonRpcResponse.model_validate(http_response.json())
        if response.error is not None:
            raise MCPJsonRpcError(response.error)
        return response

    async def close(self) -> None:
        """Закрывает внутренний HTTP клиент, если он был создан локально."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None


class MCPJsonRpcError(RuntimeError):
    """Ошибка JSON-RPC ответа от MCP server."""

    def __init__(self, error: JsonRpcError) -> None:
        self.error = error
        super().__init__(f"MCP JSON-RPC error {error.code}: {error.message}")
