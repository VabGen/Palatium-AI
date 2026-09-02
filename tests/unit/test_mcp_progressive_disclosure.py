"""Progressive MCP disclosure: summaries vs full schema."""

from __future__ import annotations

import sys

from pathlib import Path
from types import SimpleNamespace

import pytest

from palatium_ai.domain.mcp.models import MCPToolDescriptor, MCPToolSummary
from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient


def test_tool_descriptor_to_summary_omits_full_schema() -> None:
    descriptor = MCPToolDescriptor.model_validate(
        {
            "name": "search_documents",
            "description": "Find EDMS documents by query",
            "inputSchema": {
                "type": "object",
                "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}},
            },
            "side_effect": "read",
            "riskTier": "low",
        }
    )
    summary = descriptor.to_summary()
    assert summary.name == "search_documents"
    assert "EDMS" in summary.description
    assert summary.property_names == ("query", "limit")
    assert summary.side_effect == "read"
    assert not hasattr(summary, "input_schema")
    dumped = summary.model_dump()
    assert "input_schema" not in dumped
    assert "inputSchema" not in dumped


def test_mcp_tool_summary_accepts_wire_property_names() -> None:
    summary = MCPToolSummary.model_validate(
        {
            "name": "archive_document",
            "description": "Archive by id",
            "side_effect": "write",
            "riskTier": "high",
            "propertyNames": ["document_id"],
        }
    )
    assert summary.property_names == ("document_id",)
    assert summary.risk_tier == "high"


def test_stub_tools_list_omits_input_schema() -> None:
    stubs_root = Path(__file__).resolve().parents[2] / "mcp_servers"
    sys.path.insert(0, str(stubs_root))
    from mcp_stub_tools import tools_list_payload

    tools = [
        {
            "name": "search_documents",
            "description": "Search",
            "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
        }
    ]
    full = tools_list_payload(tools, None)
    assert "inputSchema" in full[0]
    slim = tools_list_payload(tools, {"omitInputSchema": True})
    assert "inputSchema" not in slim[0]
    assert slim[0]["propertyNames"] == ["query"]


def test_mcp_server_auth_tokens_are_secret_str() -> None:
    from palatium_ai.core.config.mcp import MCPConfig

    cfg = MCPConfig.model_validate(
        {
            "MCP_SERVER_AUTH_TOKENS": '{"edms":"tok-edms","analytics":"tok-analytics"}',
            "MCP_AUTH_TOKEN": "shared",
        }
    )
    assert cfg.resolve_auth_token("edms") == "tok-edms"
    assert cfg.resolve_auth_token("analytics") == "tok-analytics"
    assert cfg.resolve_auth_token("other") == "shared"
    # repr must not leak override secrets
    blob = repr(cfg.server_auth_tokens)
    assert "tok-edms" not in blob


@pytest.mark.asyncio
async def test_registry_summaries_do_not_warm_full_tools_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    """Discovery must not populate full-schema tools cache."""
    from palatium_ai.infrastructure.mcp.registry import MCPRegistry

    settings = SimpleNamespace(
        mcp=SimpleNamespace(
            servers={"edms": "http://localhost:8080"},
            timeout_seconds=5,
            allow_http_loopback=True,
            auth_required=False,
            auth_token=None,
            server_auth_tokens={},
            http_host_allowlist=lambda: frozenset({"localhost"}),
            resolve_auth_token=lambda _name: None,
        )
    )
    registry = MCPRegistry(settings=settings)
    await registry.initialize()

    async def _summaries(self: MCPJsonRpcClient) -> list[MCPToolSummary]:
        return [
            MCPToolSummary(
                name="search_documents",
                description="Search",
                side_effect="read",
                risk_tier="low",
                property_names=("query",),
            )
        ]

    async def _full(self: MCPJsonRpcClient) -> list[MCPToolDescriptor]:
        raise AssertionError("list_tools must not run during summary discovery")

    monkeypatch.setattr(MCPJsonRpcClient, "list_tool_summaries", _summaries)
    monkeypatch.setattr(MCPJsonRpcClient, "list_tools", _full)

    cards = await registry.list_tool_summaries("edms")
    assert cards[0].name == "search_documents"
    assert "edms" not in registry._tools_cache  # type: ignore[attr-defined]
    assert "edms" in registry._summaries_cache  # type: ignore[attr-defined]
