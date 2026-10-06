# tests/unit/test_platform_local_execution.py

"""Track B: platform MCP is Host-local (pin discovery, no :8082 required)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from palatium_ai.domain.mcp.execution_policy import has_local_capability, requires_local_handler
from palatium_ai.domain.mcp.models import MCPToolCall
from palatium_ai.domain.mcp.tool_policy import local_capability_tool_descriptors, schema_fingerprint
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.mcp.registry import MCPRegistry, PlatformHandlerNotWiredError
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


def _settings_remote_only() -> SimpleNamespace:
    """Compose-like profile: edms+analytics only (no platform URL)."""
    return SimpleNamespace(
        mcp=SimpleNamespace(
            servers={
                "edms": "http://127.0.0.1:8080",
                "analytics": "http://127.0.0.1:8081",
            },
            timeout_seconds=5,
            allow_http_loopback=True,
            auth_required=False,
            auth_token=None,
            server_auth_tokens={},
            http_host_allowlist=lambda: frozenset(
                {"localhost", "127.0.0.1", "::1", "mcp-edms", "mcp-analytics"},
            ),
            resolve_auth_token=lambda _name: None,
            resolve_static_token=lambda _name: None,
        )
    )


def _settings_with_platform_url() -> SimpleNamespace:
    """Legacy env that still lists platform URL — must be ignored."""
    base = _settings_remote_only()
    base.mcp.servers = {
        **base.mcp.servers,
        "platform": "http://127.0.0.1:8082",
    }
    return base


def test_requires_local_handler_platform_only() -> None:
    assert requires_local_handler("platform") is True
    assert has_local_capability("platform") is True
    assert requires_local_handler("edms") is False
    assert has_local_capability("edms") is False


@pytest.mark.asyncio()
async def test_compose_profile_without_platform_url_wires_capability() -> None:
    """Regression: Docker MCP_SERVERS without platform still has 070 tools."""
    registry = MCPRegistry(settings=_settings_remote_only())  # type: ignore[arg-type]
    await registry.initialize()
    assert registry.has_remote_url("platform") is False
    assert registry.is_registered("platform") is True
    assert "platform" in registry.list_servers()

    tools = await registry.list_tools("platform")
    names = {tool.name for tool in tools}
    assert "save_memory" in names
    assert "search_knowledge" in names
    assert len(tools) == len(local_capability_tool_descriptors("platform"))

    with pytest.raises(PlatformHandlerNotWiredError, match="platform"):
        registry.assert_local_handlers_wired()

    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        memory_port=InMemoryMemoryPort(),
    )
    registry.register_local_handler("platform", handler)
    registry.assert_local_handlers_wired()

    result = await registry.call_tool(
        "platform",
        MCPToolCall(
            name="save_memory",
            arguments={
                "user_id": "u1",
                "namespace_kind": "user",
                "scope_id": "u1",
                "entry_key": "pref",
                "value_json": '{"text":"hello"}',
                "memory_type": "preference",
            },
        ),
    )
    assert result.is_error is False


@pytest.mark.asyncio()
async def test_platform_url_in_env_is_ignored() -> None:
    registry = MCPRegistry(settings=_settings_with_platform_url())  # type: ignore[arg-type]
    await registry.initialize()
    assert registry.has_remote_url("platform") is False
    assert registry.get_server_url("platform") is None
    tools = await registry.list_tools("platform")
    assert tools


@pytest.mark.asyncio()
async def test_call_tool_platform_without_handler_raises() -> None:
    registry = MCPRegistry(settings=_settings_remote_only())  # type: ignore[arg-type]
    await registry.initialize()
    assert registry.has_local_handler("platform") is False

    with pytest.raises(PlatformHandlerNotWiredError, match="platform"):
        await registry.call_tool(
            "platform",
            MCPToolCall(
                name="save_memory",
                arguments={
                    "user_id": "u1",
                    "namespace_kind": "user",
                    "scope_id": "u1",
                    "entry_key": "k",
                    "value_json": '{"text":"x"}',
                },
            ),
        )


@pytest.mark.asyncio()
async def test_assert_local_handlers_wired_fails_without_handler() -> None:
    registry = MCPRegistry(settings=_settings_remote_only())  # type: ignore[arg-type]
    await registry.initialize()
    with pytest.raises(PlatformHandlerNotWiredError, match="platform"):
        registry.assert_local_handlers_wired()


def test_local_capability_descriptors_match_pin_fingerprints() -> None:
    from palatium_ai.domain.mcp.tool_policy import resolve_platform_pin

    for descriptor in local_capability_tool_descriptors("platform"):
        pin = resolve_platform_pin(descriptor, server_name="platform")
        assert pin is not None, descriptor.name
        assert schema_fingerprint(descriptor.input_schema) == pin.schema_fingerprint


def test_platform_stub_tools_refuse_fake_success(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    from pathlib import Path

    monkeypatch.setenv("MCP_AUTH_TOKEN", "phase2-token")
    monkeypatch.delenv("MCP_ALLOW_ANON", raising=False)
    root = Path(__file__).resolve().parents[2] / "mcp_servers"
    monkeypatch.syspath_prepend(str(root))
    monkeypatch.syspath_prepend(str(root / "platform"))
    for mod in (
        "platform_mcp_server",
        "mcp_stub_runtime",
        "mcp_stub_auth",
        "contract",
        "schema_util",
    ):
        sys.modules.pop(mod, None)

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "src"))
    import platform_mcp_server as stub  # type: ignore[import-not-found]

    with pytest.raises(PermissionError, match="discovery-only"):
        stub.save_memory(
            user_id="u",
            namespace_kind="user",
            scope_id="u",
            entry_key="k",
            value_json='{"text":"x"}',
        )
    with pytest.raises(PermissionError, match="discovery-only"):
        stub.search_knowledge(user_id="u", query="q")
    with pytest.raises(PermissionError, match="discovery-only"):
        stub.ingest_document(
            user_id="u",
            thread_id="t",
            chunks_json='[{"index":0,"text":"a"}]',
        )
