"""Researcher MCP gate: a policy decision must not be reported as a capability failure (055).

Regression (observed in the docker stack, trace d6f69a8e…): ``requires_mcp=True`` with a
route strategy other than ``direct_tool_call`` makes ``McpDiscoveryPolicy.should_attempt_tool_execution``
deny the tool path — deliberately. ``ResearcherAgent.run`` used to turn that into
``AgentOutput(status="failure", error="MCP capability unavailable")`` in ~4 ms, with zero
LLM calls, and the graph retried it three times. The node never did its actual job.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.agents.evals.cassette import (
    _packet_from_raw,
    _ResearcherEvalMcpRegistry,
    load_cassette_response,
)
from palatium_ai.application.agents.evals.static_llm import SequentialStaticLLMPort
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
from palatium_ai.application.orchestration.agent_bridge import researcher_to_agent_input
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.researcher import ResearcherInput


async def _run(harness: Harness, agent: ResearcherAgent, packet: ContextPacket, task_id: str) -> AgentOutput:
    return await harness.execute_with_guardrails(
        agent,
        researcher_to_agent_input(
            ResearcherInput(task_id=task_id, context_packet=packet),
            trace_id="regression",
            thread_id="regression",
        ),
    )


@pytest.mark.asyncio()
async def test_policy_suppressed_mcp_does_not_fail_the_node() -> None:
    """``requires_mcp`` + a non-tool strategy → answer from the LLM, not a hard failure."""
    task_id = str(uuid4())
    raw = {
        "user_text": "Summarize what Palatium is",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "requires_mcp": True,
        "requires_tool_call": False,
        "selected_strategy": "retrieve_then_reason",
    }
    packet = _packet_from_raw(raw, task_id)
    llm = SequentialStaticLLMPort([load_cassette_response("researcher/knowledge.json")])
    mcp_registry = _ResearcherEvalMcpRegistry()
    harness = Harness(llm=llm)
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=mcp_registry)

    output = await _run(harness, agent, packet, task_id)

    assert output.status != "failure", f"policy decision leaked as failure: {output.error_message}"
    assert output.error_message is None
    # The gate refused the tool path, so nothing may have been invoked.
    assert mcp_registry.calls == []


@pytest.mark.asyncio()
async def test_requires_tool_call_without_wired_registry_still_fails_closed() -> None:
    """Anti-regression: the genuine "MCP unavailable" contract must stay fail-closed."""
    task_id = str(uuid4())
    raw = {
        "user_text": "Find the contract in EDMS",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "requires_mcp": True,
        "requires_tool_call": True,
        "selected_strategy": "direct_tool_call",
        "server_name": "platform",
        "tool_name": "search_knowledge",
    }
    packet = _packet_from_raw(raw, task_id)
    llm = SequentialStaticLLMPort([load_cassette_response("researcher/knowledge.json")])
    harness = Harness(llm=llm)
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=None)

    output = await _run(harness, agent, packet, task_id)

    assert output.status == "failure"
    assert output.error_message == "MCP capability unavailable"
