"""Unit tests for McpDiscoveryPolicy gates."""

from __future__ import annotations

from palatium_ai.domain.mcp.discovery_policy import McpDiscoveryPolicy


def test_discover_blocked_when_requires_mcp_false() -> None:
    decision = McpDiscoveryPolicy.should_discover_capabilities(
        requires_mcp=False,
        route="researcher",
    )
    assert decision.allowed is False
    assert decision.reason == "requires_mcp_false"


def test_discover_blocked_for_formatter_route() -> None:
    decision = McpDiscoveryPolicy.should_discover_capabilities(
        requires_mcp=True,
        route="formatter",
    )
    assert decision.allowed is False
    assert decision.reason == "route=formatter"


def test_discover_allowed_for_researcher_requires_mcp() -> None:
    decision = McpDiscoveryPolicy.should_discover_capabilities(
        requires_mcp=True,
        route="researcher",
    )
    assert decision.allowed is True


def test_tool_execution_blocked_for_retrieve_then_reason() -> None:
    decision = McpDiscoveryPolicy.should_attempt_tool_execution(
        requires_mcp=True,
        requires_tool_call=False,
        selected_strategy="retrieve_then_reason",
    )
    assert decision.allowed is False
    assert decision.reason == "strategy=retrieve_then_reason"


def test_tool_execution_allowed_when_plan_requires_tool_call() -> None:
    decision = McpDiscoveryPolicy.should_attempt_tool_execution(
        requires_mcp=False,
        requires_tool_call=True,
        selected_strategy="retrieve_then_reason",
    )
    assert decision.allowed is True
    assert decision.reason == "plan_requires_tool_call"


def test_tool_execution_allowed_for_direct_tool_call_strategy() -> None:
    decision = McpDiscoveryPolicy.should_attempt_tool_execution(
        requires_mcp=True,
        requires_tool_call=False,
        selected_strategy="direct_tool_call",
    )
    assert decision.allowed is True
