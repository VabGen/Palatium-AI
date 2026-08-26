"""MCP JSON-RPC client: auth headers + transient retry."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from pydantic import SecretStr

from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient


def _settings(*, retry_attempts: int = 3, retry_delay: float = 0.0) -> SimpleNamespace:
    mcp = SimpleNamespace(
        auth_token=SecretStr("tok"),
        retry_attempts=retry_attempts,
        retry_delay=retry_delay,
        timeout_seconds=5,
        resolve_auth_token=lambda _name: "tok",
    )
    return SimpleNamespace(mcp=mcp)


@pytest.mark.asyncio
async def test_mcp_client_retries_transient_connect_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            raise httpx.ConnectError("boom", request=request)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": "1",
                "result": {"tools": []},
            },
        )

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = MCPJsonRpcClient(
        "http://127.0.0.1:8080/",
        _settings(retry_attempts=3, retry_delay=0.0),  # type: ignore[arg-type]
        http_client=http,
        server_name="edms",
    )
    tools = await client.list_tools()
    assert tools == []
    assert calls["n"] == 2
    await client.close()


@pytest.mark.asyncio
async def test_mcp_client_does_not_retry_unauthorized() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.headers.get("Authorization") == "Bearer tok"
        return httpx.Response(401, json={"detail": "nope"})

    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport)
    client = MCPJsonRpcClient(
        "http://127.0.0.1:8080/",
        _settings(retry_attempts=5, retry_delay=0.0),  # type: ignore[arg-type]
        http_client=http,
        server_name="edms",
    )
    with pytest.raises(httpx.HTTPStatusError):
        await client.list_tools()
    assert calls["n"] == 1
    await client.close()
