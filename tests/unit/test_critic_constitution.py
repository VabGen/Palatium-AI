"""Constitutional critic (S2): violations are merged and never skip review.

Ключевая гарантия: детерминированная статья проверяется ДО решения судьи, поэтому
пасsthrough (format_only, бюджет) не превращается в «нет проверки».
"""

from __future__ import annotations

import pytest

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.critic import CriticInput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from tests.conftest import FakeLLMPort, run_critic

_SECRET = "sk-abc123456789012345"


def _format_packet() -> ContextPacket:
    return ContextPacket(
        task_id="t-const",
        user_text="дай в виде таблицы",
        task_kind="response_formatting",
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


def _research_packet() -> ContextPacket:
    return ContextPacket(
        task_id="t-const-llm",
        user_text="Какой статус договора?",
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


@pytest.mark.asyncio()
async def test_passthrough_still_blocks_foreign_pii() -> None:
    """CriticPolicy passthrough must not bypass the constitution (fail-closed)."""
    llm = FakeLLMPort("should-not-be-called")
    before = agent_metrics.constitution_violation_count("no_pii_echo_without_permission", "deterministic")

    result = await run_critic(
        CriticInput(
            task_id="t-const",
            context_packet=_format_packet(),
            classification_confidence=0.9,
            classification_reasoning="format request",
            worker_summary="План встречи: писать на ivan.petrov@example.com",
            selected_strategy="format_only",
            continuation_kind="format",
        ),
        llm,
    )

    assert len(llm.calls) == 0
    assert result.requires_review is True
    assert result.status == "partial"
    assert result.output is not None
    assert result.output.violations == ("no_pii_echo_without_permission",)
    assert agent_metrics.constitution_violation_count("no_pii_echo_without_permission", "deterministic") == before + 1


@pytest.mark.asyncio()
async def test_secret_never_reaches_the_critic_through_context() -> None:
    """Harness redaction is the first line; the constitution's secret article is the second.

    This test pins the layering: a credential in the worker draft is stripped before
    ``run()``, so the critic neither scores it as safe prose nor needs to escalate.
    """
    llm = FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')

    result = await run_critic(
        CriticInput(
            task_id="t-const-llm",
            context_packet=_research_packet(),
            classification_confidence=0.9,
            classification_reasoning="knowledge",
            worker_summary=f"Вот ключ: {_SECRET}",
            selected_strategy="reason_only",
        ),
        llm,
    )

    assert result.output is not None
    assert result.output.violations == ()


@pytest.mark.asyncio()
async def test_judged_violation_forces_review_even_with_high_scores() -> None:
    llm = FakeLLMPort(
        '{"accuracy_score": 9, "safety_score": 9, "requires_review": false,'
        ' "summary": "ok", "violations": ["source_attribution_required"]}'
    )
    before = agent_metrics.constitution_violation_count("source_attribution_required", "judge")

    result = await run_critic(
        CriticInput(
            task_id="t-const-llm",
            context_packet=_research_packet(),
            classification_confidence=0.9,
            classification_reasoning="knowledge",
            worker_summary="Договор подписан",
            selected_strategy="reason_only",
        ),
        llm,
    )

    assert len(llm.calls) == 1
    assert result.output is not None
    assert result.output.violations == ("source_attribution_required",)
    assert result.requires_review is True
    assert result.status == "partial"
    assert agent_metrics.constitution_violation_count("source_attribution_required", "judge") == before + 1


@pytest.mark.asyncio()
async def test_judge_and_deterministic_ids_are_deduplicated() -> None:
    llm = FakeLLMPort(
        '{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok", "violations": ["no_secret_echo"]}'
    )

    result = await run_critic(
        CriticInput(
            task_id="t-const-llm",
            context_packet=_research_packet(),
            classification_confidence=0.9,
            classification_reasoning="knowledge",
            worker_summary=f"Вот ключ: {_SECRET}",
            selected_strategy="reason_only",
        ),
        llm,
    )

    assert result.output is not None
    assert result.output.violations == ("no_secret_echo",)


@pytest.mark.asyncio()
async def test_clean_turn_is_not_escalated() -> None:
    llm = FakeLLMPort('{"accuracy_score": 9, "safety_score": 9, "requires_review": false, "summary": "ok"}')

    result = await run_critic(
        CriticInput(
            task_id="t-const-llm",
            context_packet=_research_packet(),
            classification_confidence=0.9,
            classification_reasoning="knowledge",
            worker_summary="Договор подписан",
            selected_strategy="reason_only",
        ),
        llm,
    )

    assert result.requires_review is False
    assert result.status == "success"
    assert result.output is not None
    assert result.output.violations == ()
