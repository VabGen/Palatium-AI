"""Screenshot regression: analytical ask must not stub «ничего не найдено» when adaptive ON."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from palatium_ai.application.agents.researcher.outcomes import (
    required_empty_clarification_output,
    soft_empty_output,
)
from palatium_ai.application.orchestration.agent_bridge import researcher_output_to_task_result
from palatium_ai.application.orchestration.nodes import _mcp_failure_formatter_result
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.agents.messages import AgentOutput
from palatium_ai.domain.agents.researcher import (
    GROUNDING_REQUIRED_EMPTY,
    MCP_EMPTY_RESULT,
    ResearcherOutput,
    ResearcherTaskResult,
)
from palatium_ai.domain.policies.grounding import GroundingPolicy

if TYPE_CHECKING:
    import pytest

SCREENSHOT_ASK = (
    "Сравни подписку на облачный сервис и покупку коробочного ПО. "
    "Проанализируй ситуацию: продажи упали на 15%."
)


def test_screenshot_ask_is_optional_empty_degrade() -> None:
    """Policy: optional empty → degrade_reason (not stub) when adaptive enabled."""
    d = GroundingPolicy.decide_empty_retrieval(enabled=True, grounding="optional")
    assert d.action == "degrade_reason"
    assert "ничего не найдено" not in SCREENSHOT_ASK.lower()


def test_formatter_skips_empty_stub_when_adaptive_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "true")
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ROLLOUT_PCT", "100")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        state = {
            "task_id": "t1",
            "user_text": SCREENSHOT_ASK,
            "response_locale": "ru-RU",
            "classification": IntentTaskResult(
                task_id="t1",
                agent_role="intent_classifier",
                status="success",
                confidence=0.9,
                output=IntentClassifierOutput(
                    task_kind="knowledge_request",
                    requires_mcp=False,
                    candidate_capabilities=("analyze",),
                    grounding="optional",
                    confidence=0.9,
                    reasoning="analysis",
                ),
            ),
            "execution": ResearcherTaskResult(
                task_id="t1",
                agent_role="researcher",
                status="partial",
                confidence=0.0,
                requires_review=False,
                output=None,
                error=MCP_EMPTY_RESULT,
                grounding_degraded=True,
            ),
        }
        assert _mcp_failure_formatter_result(state) is None
    finally:
        get_settings.cache_clear()


def test_formatter_still_stubs_empty_when_adaptive_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "false")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        state = {
            "task_id": "t1",
            "user_text": SCREENSHOT_ASK,
            "response_locale": "ru-RU",
            "classification": IntentTaskResult(
                task_id="t1",
                agent_role="intent_classifier",
                status="success",
                confidence=0.9,
                output=IntentClassifierOutput(
                    task_kind="knowledge_request",
                    requires_mcp=False,
                    confidence=0.9,
                    reasoning="analysis",
                ),
            ),
            "execution": ResearcherTaskResult(
                task_id="t1",
                agent_role="researcher",
                status="partial",
                confidence=0.0,
                requires_review=False,
                output=None,
                error=MCP_EMPTY_RESULT,
            ),
        }
        rendered = _mcp_failure_formatter_result(state)
        assert rendered is not None
        _update, result = rendered
        assert result.output is not None
        assert result.output.plain_text() == "По запросу ничего не найдено."
    finally:
        get_settings.cache_clear()


def test_required_empty_bridge_clarifies() -> None:
    output = required_empty_clarification_output(uuid4(), question="Нужен файл.")
    result = researcher_output_to_task_result(output, task_id="t1", agent_role="researcher")
    assert result.cannot_answer_without_source is True
    assert result.error == GROUNDING_REQUIRED_EMPTY
    assert result.output is not None
    assert "файл" in result.output.summary.lower()


def test_soft_empty_still_maps_when_flag_off() -> None:
    out = soft_empty_output(uuid4(), error=MCP_EMPTY_RESULT)
    result = researcher_output_to_task_result(out, task_id="t1", agent_role="researcher")
    assert result.error == MCP_EMPTY_RESULT
    assert result.requires_review is False


def test_degraded_llm_answer_not_stubbed() -> None:
    """After optional→LLM degrade, execution has summary — Formatter must not stub."""
    output = AgentOutput(
        task_id=uuid4(),
        status="success",
        confidence=0.7,
        output=ResearcherOutput(
            summary="Облако гибче по opex; коробка — capex.",
            confidence=0.7,
            sources_used=(),
            grounding_satisfied=False,
            grounding_degraded=True,
        ),
    )
    result = researcher_output_to_task_result(output, task_id="t1", agent_role="researcher")
    assert result.grounding_degraded is True
    assert result.error is None
    assert result.output is not None
    assert "ничего не найдено" not in result.output.summary.lower()
