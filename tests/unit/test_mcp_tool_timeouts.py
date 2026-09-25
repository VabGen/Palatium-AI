"""Per-tool MCP timeouts (P1-8, 070): config resolution + agent-budget invariant."""

from __future__ import annotations

import asyncio

from types import SimpleNamespace

import pytest

from palatium_ai.core.config.mcp import MCPConfig
from palatium_ai.domain.mcp.models import MCPToolCall
from palatium_ai.domain.mcp.timeout_policy import (
    McpAgentBudget,
    McpTimeoutBudgetError,
    assert_tool_timeouts_within_agent_budget,
    mcp_tool_keys,
)
from palatium_ai.infrastructure.mcp.base import MCPJsonRpcClient, MCPJsonRpcError


def _config(**overrides: str) -> MCPConfig:
    return MCPConfig.model_validate(overrides)


def test_resolve_tool_timeout_precedence() -> None:
    config = _config(
        MCP_TIMEOUT_SECONDS="30",
        MCP_TOOL_TIMEOUT_SECONDS='{"default": 25, "search_documents": 20, "edms.search_documents": 10}',
    )
    assert config.resolve_tool_timeout("edms", "search_documents") == 10  # most specific
    assert config.resolve_tool_timeout("analytics", "search_documents") == 20  # bare tool
    assert config.resolve_tool_timeout("edms", "other") == 25  # default key
    assert config.resolve_tool_timeout("edms", "unused") == 25


def test_resolve_tool_timeout_falls_back_to_global_timeout() -> None:
    config = _config(MCP_TIMEOUT_SECONDS="30", MCP_TOOL_TIMEOUT_SECONDS='{"edms.search_documents": 10}')
    assert config.resolve_tool_timeout("analytics", "get_sales_metrics") == 30


def test_tool_timeouts_accept_dict_env() -> None:
    config = _config(MCP_TOOL_TIMEOUT_SECONDS={"edms.search_documents": "15"})
    assert config.resolve_tool_timeout("edms", "search_documents") == 15


@pytest.mark.parametrize("raw", ['{"edms.search_documents": 0}', '{"edms.search_documents": -1}'])
def test_tool_timeouts_reject_non_positive(raw: str) -> None:
    with pytest.raises(ValueError):
        _config(MCP_TOOL_TIMEOUT_SECONDS=raw)


def test_tool_timeouts_reject_non_integer() -> None:
    with pytest.raises(ValueError):
        _config(MCP_TOOL_TIMEOUT_SECONDS='{"edms.search_documents": "soon"}')


# --- client wiring: the resolved per-tool timeout drives the actual tools/call ---


class _SlowCallClient:
    """Stand-in for ``fastmcp.Client`` whose tools/call outlives the timeout."""

    calls: list[str] = []

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self) -> _SlowCallClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def call_tool(self, name: str, arguments: object) -> object:
        self.__class__.calls.append(name)
        await asyncio.sleep(5)
        return SimpleNamespace(content=[], is_error=False)


def _settings(tool_timeouts: dict[str, int], *, timeout_seconds: float = 5.0) -> SimpleNamespace:
    # `timeout_seconds` may be sub-second here (tight-timeout tests), so this stays a
    # double instead of a real MCPConfig (whose MCP_TOOL_TIMEOUT_SECONDS is int-only) —
    # but it must still expose the auth surface the client resolves (070).
    mcp = SimpleNamespace(
        timeout_seconds=timeout_seconds,
        retry_attempts=1,
        retry_delay=0.0,
        auth_token=None,
        server_auth_tokens={},
        resolve_tool_timeout=lambda server, tool: tool_timeouts.get(f"{server}.{tool}", timeout_seconds),
    )
    return SimpleNamespace(mcp=mcp)


@pytest.mark.asyncio
async def test_call_tool_uses_per_tool_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A slow tool must honour its own (tight) timeout, not the global one."""
    monkeypatch.setattr("fastmcp.Client", _SlowCallClient)
    _SlowCallClient.calls = []
    client = MCPJsonRpcClient(
        "http://127.0.0.1:8080/",
        _settings({"edms.fast_tool": 0.01}, timeout_seconds=30.0),  # type: ignore[arg-type]
        server_name="edms",
    )
    with pytest.raises(MCPJsonRpcError, match="timed out"):
        await client.call_tool(MCPToolCall(name="fast_tool", arguments={}))
    assert _SlowCallClient.calls == ["fast_tool"]


# --- startup invariant: tool timeout must be below the calling agent budget ---


def test_mcp_tool_keys_extracts_server_tool() -> None:
    keys = mcp_tool_keys(("mcp:edms.search_documents", "plan", "mcp:platform.graph_query", "mcp:"))
    assert keys == frozenset({"edms.search_documents", "platform.graph_query"})


def test_budget_invariant_accepts_current_defaults() -> None:
    budgets = (
        McpAgentBudget("researcher", 90, frozenset({"edms.search_documents"})),
        McpAgentBudget("text_ingestor", 120, frozenset({"platform.ingest_document"})),
    )
    assert_tool_timeouts_within_agent_budget(
        default_timeout_seconds=30,
        tool_timeouts={"edms.search_documents": 15},
        agent_budgets=budgets,
    )


def test_budget_invariant_rejects_tool_exceeding_calling_agent() -> None:
    budgets = (McpAgentBudget("researcher", 90, frozenset({"edms.search_documents"})),)
    with pytest.raises(McpTimeoutBudgetError, match="edms.search_documents"):
        assert_tool_timeouts_within_agent_budget(
            default_timeout_seconds=30,
            tool_timeouts={"edms.search_documents": 90},
            agent_budgets=budgets,
        )


def test_budget_invariant_rejects_default_exceeding_tightest_mcp_agent() -> None:
    budgets = (McpAgentBudget("researcher", 30, frozenset({"edms.search_documents"})),)
    with pytest.raises(McpTimeoutBudgetError, match="default"):
        assert_tool_timeouts_within_agent_budget(
            default_timeout_seconds=30,
            tool_timeouts={},
            agent_budgets=budgets,
        )


def test_budget_invariant_ignores_tools_no_agent_calls() -> None:
    budgets = (McpAgentBudget("researcher", 90, frozenset({"edms.search_documents"})),)
    # Only bare "tool" matching may apply; an unrelated specific key is not attributable.
    assert_tool_timeouts_within_agent_budget(
        default_timeout_seconds=30,
        tool_timeouts={"analytics.get_sales_metrics": 500},
        agent_budgets=budgets,
    )


def test_budget_invariant_bare_tool_key_matches_any_server() -> None:
    budgets = (McpAgentBudget("researcher", 90, frozenset({"edms.search_documents"})),)
    with pytest.raises(McpTimeoutBudgetError, match="search_documents"):
        assert_tool_timeouts_within_agent_budget(
            default_timeout_seconds=30,
            tool_timeouts={"search_documents": 120},
            agent_budgets=budgets,
        )


# --- composition root: the guard is actually invoked with settings (050: no dead config) ---


def test_wiring_guard_accepts_default_config() -> None:
    from palatium_ai.application.wiring import _assert_mcp_timeout_budget

    _assert_mcp_timeout_budget(SimpleNamespace(mcp=_config(MCP_TIMEOUT_SECONDS="30")))


def test_wiring_guard_rejects_timeout_above_calling_agent() -> None:
    from palatium_ai.application.wiring import _assert_mcp_timeout_budget

    config = _config(
        MCP_TIMEOUT_SECONDS="30",
        MCP_TOOL_TIMEOUT_SECONDS='{"edms.search_documents": 120}',
    )
    with pytest.raises(McpTimeoutBudgetError, match="edms.search_documents"):
        _assert_mcp_timeout_budget(SimpleNamespace(mcp=config))


def test_wiring_guard_skips_when_mcp_disabled() -> None:
    from palatium_ai.application.wiring import _assert_mcp_timeout_budget

    config = _config(MCP_ENABLED="false", MCP_TIMEOUT_SECONDS="120")
    _assert_mcp_timeout_budget(SimpleNamespace(mcp=config))
