"""Unit tests for MCP registry graceful degradation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest

from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient
from palatium_ai.infrastructure.mcp.registry import MCPRegistry


def _settings() -> Any:
    return SimpleNamespace(
        mcp=SimpleNamespace(
            servers={"edms": "http://localhost:8080", "analytics": "http://localhost:8081"},
            timeout_seconds=5,
            allow_http_loopback=True,
            auth_required=False,
            auth_token=None,
            server_auth_tokens={},
            http_host_allowlist=lambda: frozenset({"localhost", "127.0.0.1", "::1", "mcp-edms", "mcp-analytics"}),
            resolve_auth_token=lambda _name: None,
        )
    )


@pytest.mark.asyncio
async def test_list_tools_returns_empty_when_server_unreachable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unreachable MCP servers must not crash discovery."""
    registry = MCPRegistry(settings=_settings())
    await registry.initialize()
    calls = {"n": 0}

    async def _fail_list_tools(self: MCPJsonRpcClient) -> list[object]:
        calls["n"] += 1
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(MCPJsonRpcClient, "list_tools", _fail_list_tools)

    tools = await registry.list_tools("analytics")
    tools_again = await registry.list_tools("analytics")

    assert tools == []
    assert tools_again == []
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_list_tools_opens_circuit_after_three_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    """Circuit opens after 3 consecutive failures (platform breaker)."""
    registry = MCPRegistry(settings=_settings())
    await registry.initialize()
    calls = {"n": 0}

    async def _fail_list_tools(self: MCPJsonRpcClient) -> list[object]:
        calls["n"] += 1
        raise httpx.ConnectError("connection failed")

    monkeypatch.setattr(MCPJsonRpcClient, "list_tools", _fail_list_tools)

    for _ in range(3):
        registry._tools_cache.clear()  # type: ignore[attr-defined]
        await registry.list_tools("edms", force_refresh=True)

    before = calls["n"]
    await registry.list_tools("edms", force_refresh=True)
    assert calls["n"] == before


@pytest.mark.asyncio
async def test_list_tools_still_returns_tools_from_available_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """Other servers should keep working when one server is down."""
    from palatium_ai.domain.mcp.models import MCPToolDescriptor

    registry = MCPRegistry(settings=_settings())
    await registry.initialize()
    expected = [
        MCPToolDescriptor(
            name="search_documents",
            description="Search EDMS documents by query string.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        )
    ]

    async def _conditional_list_tools(self: MCPJsonRpcClient) -> list[MCPToolDescriptor]:
        if self._server_url.endswith(":8081"):
            raise httpx.ConnectError("analytics down")
        return expected

    monkeypatch.setattr(MCPJsonRpcClient, "list_tools", _conditional_list_tools)

    analytics_tools = await registry.list_tools("analytics")
    edms_tools = await registry.list_tools("edms")

    assert analytics_tools == []
    assert len(edms_tools) == 1
    assert edms_tools[0].name == "search_documents"
