"""MCP agent loop: synthesize non-empty results, fail closed on empty and errors."""

from __future__ import annotations

import json

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
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.researcher import MCP_EMPTY_RESULT, MCP_TOOL_ERROR, ResearcherInput, ResearcherOutput
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output
from palatium_ai.domain.policies.types import VERBATIM_EXTRACTION_CAPABILITY

_SYNTHESIS = json.dumps(
    {
        "summary": "Архитектура описана в найденном фрагменте.",
        "confidence": 0.91,
        "sources_used": ["mcp:platform.search_knowledge"],
    },
    ensure_ascii=False,
)


class _TextRegistry(_ResearcherEvalMcpRegistry):
    def __init__(self, text: str, *, is_error: bool = False) -> None:
        super().__init__()
        self._text = text
        self._is_error = is_error

    async def call_tool(
        self,
        server_name: str,
        tool_call: MCPToolCall,
        *,
        allow_unpinned: bool = False,
    ) -> MCPToolResult:
        _ = allow_unpinned
        self.calls.append((server_name, tool_call))
        return MCPToolResult(
            content=[{"type": "text", "text": self._text}],
            is_error=self._is_error,
        )


def _packet(task_id: str, **extra: object):
    raw: dict[str, object] = {
        "user_text": "найди архитектуру",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "requires_mcp": True,
        "requires_tool_call": True,
        "selected_strategy": "direct_tool_call",
        "server_name": "platform",
        "tool_name": "search_knowledge",
    }
    raw.update(extra)
    return _packet_from_raw(raw, task_id)


async def _run(
    text: str, *, is_error: bool = False, capabilities: tuple[str, ...] = ()
) -> tuple[AgentOutput, SequentialStaticLLMPort]:
    task_id = str(uuid4())
    llm = SequentialStaticLLMPort([load_cassette_response("researcher/search_knowledge_args.json"), _SYNTHESIS])
    registry = _TextRegistry(text, is_error=is_error)
    harness = Harness(llm=llm)
    agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=registry)
    output = await harness.execute_with_guardrails(
        agent,
        researcher_to_agent_input(
            ResearcherInput(task_id=task_id, context_packet=_packet(task_id, candidate_capabilities=capabilities)),
            trace_id="mcp-loop",
            thread_id="mcp-loop",
            user_id="eval-user",
        ),
    )
    return output, llm


@pytest.mark.asyncio()
async def test_mcp_success_second_llm_call_hides_envelope() -> None:
    payload = json.dumps({"hit_count": 1, "hits": [{"text": "слои платформы"}]}, ensure_ascii=False)
    output, llm = await _run(payload)

    assert output.status == "success"
    assert output.error_message is None
    assert isinstance(output.output, ResearcherOutput)
    assert output.output.summary == "Архитектура описана в найденном фрагменте."
    assert output.output.confidence == pytest.approx(0.91)
    assert output.output.sources_used == ("mcp:platform.search_knowledge",)
    assert "UNTRUSTED_TOOL_OUTPUT" not in output.output.summary
    assert len(llm.calls) == 2
    synthesis = llm.calls[1][-1].content
    assert "UNTRUSTED_TOOL_OUTPUT" in synthesis


@pytest.mark.asyncio()
async def test_mcp_empty_skips_synthesis() -> None:
    output, llm = await _run(json.dumps({"hit_count": 0, "hits": []}))

    assert output.status == "partial"
    assert output.error_message == MCP_EMPTY_RESULT
    assert len(llm.calls) == 1


@pytest.mark.asyncio()
async def test_mcp_error_skips_synthesis() -> None:
    output, llm = await _run("tool failed", is_error=True)

    assert output.status == "failure"
    assert output.error_message == MCP_TOOL_ERROR
    assert isinstance(output.output, ResearcherOutput)
    assert "UNTRUSTED_TOOL_OUTPUT" not in output.output.summary
    assert len(llm.calls) == 1


@pytest.mark.asyncio()
async def test_verbatim_strips_envelope_without_second_llm_call() -> None:
    fenced = wrap_untrusted_tool_output("Точный текст файла.", source="attachment:doc")
    output, llm = await _run(fenced, capabilities=(VERBATIM_EXTRACTION_CAPABILITY,))

    assert output.status != "failure"
    assert isinstance(output.output, ResearcherOutput)
    assert output.output.summary == "Точный текст файла."
    assert "UNTRUSTED_TOOL_OUTPUT" not in output.output.summary
    assert output.output.sources_used == ("mcp:platform.search_knowledge",)
    assert len(llm.calls) == 1
