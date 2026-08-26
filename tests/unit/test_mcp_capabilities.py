"""Unit tests for MCP capability discovery resilience."""

from __future__ import annotations

import httpx
import pytest

from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from tests.conftest import FakeMCPRegistry


class _PartialFailureRegistry(FakeMCPRegistry):
    async def list_tools(self, server_name: str, *, force_refresh: bool = False) -> list[object]:
        if server_name == "analytics":
            raise httpx.ConnectError("analytics down")
        return await super().list_tools(server_name, force_refresh=force_refresh)


@pytest.mark.asyncio
async def test_discover_skips_failed_server_and_keeps_available_capabilities() -> None:
    """Capability discovery should continue when one MCP server fails."""
    registry = _PartialFailureRegistry()
    registry._tools["analytics"] = []  # type: ignore[attr-defined]

    index = MCPCapabilityIndex(registry)
    bindings = await index.discover()

    assert any(binding.server_name == "edms" for binding in bindings)
    assert all(binding.server_name != "analytics" for binding in bindings)


@pytest.mark.asyncio
async def test_resolve_best_requires_task_text_evidence() -> None:
    """Intent capability tags alone must not bind a tool (false MCP on rewrite/knowledge)."""
    registry = FakeMCPRegistry()
    index = MCPCapabilityIndex(registry)

    # RU rewrite follow-up: no lexical overlap with English EDMS tool descriptors.
    none_bound = await index.resolve_best(
        "напиши ответ ссылаясь на законодательство",
        ("search", "retrieve"),
    )
    assert none_bound is None

    # Explicit EDMS/search ask with English terms overlapping the tool.
    bound = await index.resolve_best(
        "Search EDMS documents for the contract",
        ("search",),
    )
    assert bound is not None
    assert bound.server_name == "edms"
    assert bound.tool_name == "search_documents"
