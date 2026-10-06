"""MCP client: auth + transient retry (FastMCP Client adapter)."""

from __future__ import annotations

import asyncio

from types import SimpleNamespace

import httpx
import pytest

from palatium_ai.domain.mcp.models import MCPToolCall
from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient, MCPJsonRpcError


def _settings(*, retry_attempts: int = 3, retry_delay: float = 0.0, timeout_seconds: float = 5.0) -> SimpleNamespace:
    # Real MCPConfig (env-file disabled) — a `SimpleNamespace` double drifts from the
    # contract and silently resolved the bearer to None (070/000).
    from palatium_ai.core.config.mcp import MCPConfig

    mcp = MCPConfig(
        _env_file=None,  # type: ignore[call-arg]
        auth_token="tok",
        retry_attempts=retry_attempts,
        retry_delay=retry_delay,
        timeout_seconds=int(timeout_seconds),
    )
    return SimpleNamespace(mcp=mcp)


class _FakeFastMcpClient:
    """Minimal async context manager standing in for fastmcp.Client."""

    behavior: list[BaseException | list[object]] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self) -> _FakeFastMcpClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def list_tools(self) -> list[object]:
        queue = self.__class__.behavior
        if not queue:
            return []
        item = queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


@pytest.mark.asyncio()
async def test_mcp_client_retries_transient_connect_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8080/")
    _FakeFastMcpClient.behavior = [
        httpx.ConnectError("boom", request=request),
        [],
    ]
    monkeypatch.setattr("fastmcp.Client", _FakeFastMcpClient)
    client = MCPJsonRpcClient(
        "http://127.0.0.1:8080/",
        _settings(retry_attempts=3, retry_delay=0.0),  # type: ignore[arg-type]
        server_name="edms",
    )
    tools = await client.list_tools()
    assert tools == []
    assert _FakeFastMcpClient.behavior == []


@pytest.mark.asyncio()
async def test_mcp_client_does_not_retry_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "http://127.0.0.1:8080/")
    response = httpx.Response(401, request=request)
    _FakeFastMcpClient.behavior = [httpx.HTTPStatusError("nope", request=request, response=response)]
    monkeypatch.setattr("fastmcp.Client", _FakeFastMcpClient)

    seen_auth: list[object] = []

    class _CaptureClient(_FakeFastMcpClient):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            seen_auth.append(kwargs.get("auth"))

    monkeypatch.setattr("fastmcp.Client", _CaptureClient)
    _CaptureClient.behavior = [httpx.HTTPStatusError("nope", request=request, response=response)]

    client = MCPJsonRpcClient(
        "http://127.0.0.1:8080/",
        _settings(retry_attempts=5, retry_delay=0.0),  # type: ignore[arg-type]
        server_name="edms",
    )
    with pytest.raises((httpx.HTTPStatusError, MCPJsonRpcError)):
        await client.list_tools()
    assert seen_auth == ["tok"]
    assert len(_CaptureClient.behavior) == 0  # raised on first attempt; queue empty after pop


class _SlowCallClient(_FakeFastMcpClient):
    """Client whose tools/call never returns inside the configured timeout."""

    async def call_tool(self, name: str, arguments: object) -> object:
        await asyncio.sleep(5)
        return SimpleNamespace(content=[], is_error=False)


@pytest.mark.asyncio()
async def test_mcp_client_call_tool_enforces_configured_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """050: a hung upstream must surface as a typed MCP error, not hang the agent."""
    monkeypatch.setattr("fastmcp.Client", _SlowCallClient)
    client = MCPJsonRpcClient(
        "http://127.0.0.1:8080/",
        _settings(retry_attempts=1, retry_delay=0.0, timeout_seconds=0.05),  # type: ignore[arg-type]
        server_name="edms",
    )
    with pytest.raises(MCPJsonRpcError, match="timed out"):
        await client.call_tool(MCPToolCall(name="slow_tool", arguments={}))
