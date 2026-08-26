# tests/unit/test_context_weaver.py

"""Тесты для ContextWeaver foundation."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.context_weaver_agent import ContextWeaverAgent
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput
from palatium_ai.domain.agents.contracts import AgentContext
from tests.conftest import FakeMCPRegistry


@pytest.mark.asyncio
async def test_context_weaver_returns_context_packet_and_execution_bundle() -> None:
    """ContextWeaver должен отдавать нормализованный packet и bundle."""
    agent = ContextWeaverAgent(mcp_registry=FakeMCPRegistry())
    task_input = ContextWeaverInput(
        task_id="ctx-1",
        user_text="Find the contract in EDMS",
        task_kind="tool_execution",
        route="researcher",
        route_plan="Resolve capability and call the matching MCP tool.",
        requires_mcp=True,
        candidate_capabilities=("search",),
    )

    result = await agent.execute(task_input, AgentContext(thread_id="thread-ctx-1"))

    assert result.output is not None
    assert result.output.context_packet.task_id == "ctx-1"
    assert result.output.context_packet.execution_plan.strategy == "direct_tool_call"
    assert result.output.execution_bundle.selected_strategy == "direct_tool_call"
    assert result.output.execution_bundle.requires_tool_call is True
    assert result.output.execution_bundle.steps[0].tool_name == "search_documents"
