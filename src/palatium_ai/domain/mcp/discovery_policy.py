# src/palatium_ai/domain/mcp/discovery_policy.py

"""When MCP network discovery / tool execution is allowed on the hot path.

Pure domain policy — no HTTP, no phrase lists. Gates expensive tools/list and tool calls
so social/format/clarify paths and retrieve_then_reason never spin on dead MCP stubs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from palatium_ai.domain.agents.supervisor import WorkerRoute
    from palatium_ai.domain.mcp.models import ExecutionStrategy


class McpDiscoveryDecision(BaseModel):
    """Outcome of McpDiscoveryPolicy for one turn."""

    model_config = {"frozen": True}

    allowed: bool
    reason: str = Field(min_length=1, max_length=128)


class McpDiscoveryPolicy:
    """Capability discovery vs tool execution gates."""

    @staticmethod
    def should_discover_capabilities(
        *,
        requires_mcp: bool,
        route: WorkerRoute,
    ) -> McpDiscoveryDecision:
        """Whether ExecutionPlanner may call MCPCapabilityIndex (tools/list fan-out)."""
        if not requires_mcp:
            return McpDiscoveryDecision(allowed=False, reason="requires_mcp_false")
        if route != "researcher":
            return McpDiscoveryDecision(allowed=False, reason=f"route={route}")
        return McpDiscoveryDecision(allowed=True, reason="researcher_requires_mcp")

    @staticmethod
    def should_attempt_tool_execution(
        *,
        requires_mcp: bool,
        requires_tool_call: bool,
        selected_strategy: ExecutionStrategy,
    ) -> McpDiscoveryDecision:
        """Whether Researcher may invoke MCP before LLM reasoning."""
        if requires_tool_call:
            return McpDiscoveryDecision(allowed=True, reason="plan_requires_tool_call")
        if not requires_mcp:
            return McpDiscoveryDecision(allowed=False, reason="requires_mcp_false")
        if selected_strategy == "direct_tool_call":
            return McpDiscoveryDecision(allowed=True, reason="direct_tool_call_strategy")
        return McpDiscoveryDecision(allowed=False, reason=f"strategy={selected_strategy}")
