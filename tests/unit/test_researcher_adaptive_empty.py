"""Researcher empty MCP → adaptive degrade / clarify / flag-off stub."""

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
from palatium_ai.domain.agents.researcher import (
    GROUNDING_REQUIRED_EMPTY,
    MCP_EMPTY_RESULT,
    ResearcherInput,
    ResearcherOutput,
)
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult


class _EmptyRegistry(_ResearcherEvalMcpRegistry):
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
            content=[{"type": "text", "text": json.dumps({"hit_count": 0, "hits": []})}],
            is_error=False,
        )


def _packet(task_id: str, *, grounding: str, user_text: str):
    return _packet_from_raw(
        {
            "user_text": user_text,
            "task_kind": "knowledge_request",
            "route": "researcher",
            "requires_mcp": False,
            "requires_tool_call": True,
            "selected_strategy": "retrieve_then_reason",
            "server_name": "platform",
            "tool_name": "search_knowledge",
            "grounding": grounding,
        },
        task_id,
    )


@pytest.mark.asyncio()
async def test_optional_empty_degrades_to_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        task_id = str(uuid4())
        degrade = json.dumps(
            {
                "summary": "Сравнение без корпуса: opex vs capex.",
                "confidence": 0.85,
                "sources_used": ["llm_ungrounded"],
            },
            ensure_ascii=False,
        )
        llm = SequentialStaticLLMPort(
            [load_cassette_response("researcher/search_knowledge_args.json"), degrade],
        )
        harness = Harness(llm=llm)
        agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=_EmptyRegistry())
        output = await harness.execute_with_guardrails(
            agent,
            researcher_to_agent_input(
                ResearcherInput(
                    task_id=task_id,
                    context_packet=_packet(
                        task_id,
                        grounding="optional",
                        user_text="сравни облако и on-prem",
                    ),
                ),
                trace_id="ag-opt",
                thread_id="ag-opt",
                user_id="eval-user",
            ),
        )
        assert output.error_message != MCP_EMPTY_RESULT
        assert isinstance(output.output, ResearcherOutput)
        assert output.output.grounding_degraded is True
        assert "opex" in output.output.summary.lower() or "сравнен" in output.output.summary.lower()
        assert len(llm.calls) == 2
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio()
async def test_required_empty_clarifies_with_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        task_id = str(uuid4())
        ask = "что в моём загруженном файле отчёт.docx?"
        llm = SequentialStaticLLMPort(
            [load_cassette_response("researcher/search_knowledge_args.json")],
        )
        harness = Harness(llm=llm)
        agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=_EmptyRegistry())
        output = await harness.execute_with_guardrails(
            agent,
            researcher_to_agent_input(
                ResearcherInput(
                    task_id=task_id,
                    context_packet=_packet(task_id, grounding="required", user_text=ask),
                ),
                trace_id="ag-req",
                thread_id="ag-req",
                user_id="eval-user",
            ),
        )
        assert output.error_message == GROUNDING_REQUIRED_EMPTY
        assert isinstance(output.output, ResearcherOutput)
        assert output.output.cannot_answer_without_source is True
        assert "отчёт.docx" in output.output.summary or "файле" in output.output.summary
        assert "По запросу" in output.output.summary
    finally:
        get_settings.cache_clear()


@pytest.mark.asyncio()
async def test_flag_off_logs_fallback_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify researcher.grounding_stub emits fallback_disabled when adaptive OFF."""
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "false")
    from unittest.mock import MagicMock, patch

    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        task_id = str(uuid4())
        soft = json.dumps(
            {
                "summary": "По запросу ничего не найдено.",
                "confidence": 0.0,
                "sources_used": [],
            },
            ensure_ascii=False,
        )
        llm = SequentialStaticLLMPort(
            [load_cassette_response("researcher/search_knowledge_args.json"), soft],
        )
        harness = Harness(llm=llm)
        agent = ResearcherAgent(harness, RESEARCHER_CONFIG, llm, mcp_registry=_EmptyRegistry())
        mock_log = MagicMock()
        with patch("palatium_ai.application.agents.researcher.agent.logger", mock_log):
            output = await harness.execute_with_guardrails(
                agent,
                researcher_to_agent_input(
                    ResearcherInput(
                        task_id=task_id,
                        context_packet=_packet(
                            task_id,
                            grounding="optional",
                            user_text="сравни облако и коробку",
                        ),
                    ),
                    trace_id="ag-off",
                    thread_id="ag-off",
                    user_id="eval-user",
                ),
            )
        warning_calls = [c for c in mock_log.warning.call_args_list if c.args and c.args[0] == "researcher.grounding_stub"]
        assert warning_calls, "expected researcher.grounding_stub warning when flag OFF"
        assert warning_calls[0].kwargs.get("fallback_disabled") is True
        assert output.error_message == MCP_EMPTY_RESULT or (isinstance(output.output, ResearcherOutput) and output.output.summary)
    finally:
        get_settings.cache_clear()
