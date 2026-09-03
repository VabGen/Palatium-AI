"""Critic format_only passthrough (no false HITL on rewrite follow-ups)."""

from __future__ import annotations

import pytest

from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.critic import CriticInput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from tests.conftest import FakeLLMPort, run_critic


def _packet(*, task_kind: str = "response_formatting") -> ContextPacket:
    return ContextPacket(
        task_id="t1",
        user_text="дай в виде таблицы",
        task_kind=task_kind,  # type: ignore[arg-type]
        route="formatter",
        route_plan="Format prior answer",
        requires_mcp=False,
        candidate_capabilities=("format",),
        execution_plan=ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="format continuation",
        ),
        context_summary="format_only",
    )


@pytest.mark.asyncio
async def test_critic_skips_llm_for_format_only_with_prior_content() -> None:
    llm = FakeLLMPort("should-not-be-called")
    result = await run_critic(
        CriticInput(
            task_id="t1",
            context_packet=_packet(),
            classification_confidence=0.9,
            classification_reasoning="format request",
            worker_summary="План встречи:\n1. Цель\n2. Повестка",
            selected_strategy="format_only",
            continuation_kind="format",
        ),
        llm,
    )
    assert result.status == "success"
    assert result.requires_review is False
    assert result.output is not None
    assert result.output.accuracy_score >= 8
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_critic_skips_llm_for_ack_only_social() -> None:
    llm = FakeLLMPort("should-not-be-called")
    packet = ContextPacket(
        task_id="t3",
        user_text="привет",
        task_kind="social_conversation",
        route="formatter",
        route_plan="Short social reply",
        requires_mcp=False,
        candidate_capabilities=(),
        execution_plan=ToolExecutionPlan(
            strategy="ack_only",
            requires_tool_call=False,
            rationale="social",
        ),
        context_summary="ack_only",
    )
    result = await run_critic(
        CriticInput(
            task_id="t3",
            context_packet=packet,
            classification_confidence=0.95,
            classification_reasoning="greeting",
            worker_summary=None,
            selected_strategy="ack_only",
            continuation_kind="new_topic",
        ),
        llm,
    )
    assert result.status == "success"
    assert result.requires_review is False
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_critic_still_calls_llm_for_research_path() -> None:
    llm = FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')
    packet = ContextPacket(
        task_id="t2",
        user_text="What is the contract status?",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="Research then answer",
        requires_mcp=False,
        candidate_capabilities=("summarize",),
        execution_plan=ToolExecutionPlan(
            strategy="reason_only",
            requires_tool_call=False,
            rationale="reason",
        ),
        context_summary="reason_only",
    )
    result = await run_critic(
        CriticInput(
            task_id="t2",
            context_packet=packet,
            classification_confidence=0.9,
            classification_reasoning="knowledge",
            worker_summary="Contract is signed",
            selected_strategy="reason_only",
        ),
        llm,
    )
    assert result.status == "success"
    assert len(llm.calls) == 1
