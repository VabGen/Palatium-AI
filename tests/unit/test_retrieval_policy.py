"""Unit tests for RetrievalPolicy (web_fallback last-resort gating)."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.domain.mcp.models import MCPToolSummary
from palatium_ai.domain.policies.retrieval import RetrievalPolicy
from tests.conftest import FakeMCPRegistry


def test_web_fallback_blocked_without_empty_local() -> None:
    decision = RetrievalPolicy.may_bind_tool(tool_name="web_fallback", local_retrieval_empty=False)
    assert decision.allowed is False
    assert decision.reason == "web_fallback_requires_empty_local"


def test_web_fallback_allowed_when_local_empty() -> None:
    decision = RetrievalPolicy.may_bind_tool(tool_name="web_fallback", local_retrieval_empty=True)
    assert decision.allowed is True
    assert decision.reason == "local_retrieval_empty"


def test_non_last_resort_tools_always_allowed() -> None:
    decision = RetrievalPolicy.may_bind_tool(tool_name="search_knowledge", local_retrieval_empty=False)
    assert decision.allowed is True


class _PlatformWebRegistry(FakeMCPRegistry):
    async def list_tool_summaries(self, server_name: str, *, force_refresh: bool = False) -> list[object]:
        if server_name != "platform":
            return await super().list_tool_summaries(server_name, force_refresh=force_refresh)
        return [
            MCPToolSummary(
                name="web_fallback",
                description="External web search after local knowledge and memory retrieval returned empty.",
                property_names=("user_id", "query", "max_results"),
            )
        ]


@pytest.mark.asyncio
async def test_capability_index_skips_web_fallback_until_local_empty() -> None:
    registry = _PlatformWebRegistry()
    index = MCPCapabilityIndex(registry)

    blocked = await index.resolve_best(
        "web search fallback after empty local knowledge",
        ("search",),
        local_retrieval_empty=False,
    )
    assert blocked is None

    allowed = await index.resolve_best(
        "web search fallback after empty local knowledge",
        ("search",),
        local_retrieval_empty=True,
    )
    assert allowed is not None
    assert allowed.tool_name == "web_fallback"


@pytest.mark.asyncio
async def test_researcher_blocks_web_fallback_without_local_empty_flag() -> None:
    from uuid import uuid4

    from palatium_ai.application.agents.evals.cassette import (
        _packet_from_raw,
        _ResearcherEvalMcpRegistry,
        load_cassette_response,
    )
    from palatium_ai.application.agents.evals.static_llm import SequentialStaticLLMPort
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.researcher import RESEARCHER_CONFIG, ResearcherAgent
    from palatium_ai.application.orchestration.agent_bridge import researcher_to_agent_input
    from palatium_ai.domain.agents.researcher import ResearcherInput

    task_id = str(uuid4())
    raw = {
        "user_text": "web search fallback",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "requires_mcp": True,
        "requires_tool_call": True,
        "selected_strategy": "direct_tool_call",
        "server_name": "platform",
        "tool_name": "web_fallback",
        "local_retrieval_empty": False,
    }
    packet = _packet_from_raw(raw, task_id)
    llm = SequentialStaticLLMPort([load_cassette_response("researcher/web_fallback_args.json")])
    mcp_registry = _ResearcherEvalMcpRegistry()
    harness = Harness(llm=llm)
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=mcp_registry)
    output = await harness.execute_with_guardrails(
        agent,
        researcher_to_agent_input(
            ResearcherInput(task_id=task_id, context_packet=packet),
            trace_id="eval",
            thread_id="eval",
        ),
    )
    assert output.status == "failure"
    assert mcp_registry.calls == []
