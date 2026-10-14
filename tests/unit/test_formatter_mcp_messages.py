"""Localized MCP empty/error copy, and Formatter presenting it from execution.error."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.application.agents.formatter.messages import localized_message
from palatium_ai.application.orchestration.nodes import _mcp_failure_formatter_result
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.agents.researcher import MCP_EMPTY_RESULT, MCP_TOOL_ERROR, ResearcherTaskResult

if TYPE_CHECKING:
    import pytest


def test_localized_message_distinguishes_locale_and_reason() -> None:
    assert localized_message("ru-RU", MCP_EMPTY_RESULT) == "По запросу ничего не найдено."
    assert localized_message("en-US", MCP_EMPTY_RESULT) == "No results found for the request."
    assert localized_message("ru-RU", MCP_TOOL_ERROR) == "Не удалось получить данные. Попробуйте позже."
    assert localized_message("en-US", MCP_TOOL_ERROR) == "Could not retrieve data. Try again later."


def test_localized_message_uses_script_default() -> None:
    assert localized_message("uk-UA", MCP_EMPTY_RESULT) == "По запросу ничего не найдено."
    assert localized_message("de", MCP_TOOL_ERROR) == "Could not retrieve data. Try again later."
    assert localized_message("und", MCP_EMPTY_RESULT, user_text="найди темы") == "По запросу ничего не найдено."


def test_formatter_renders_mcp_empty_from_execution_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag OFF (default): soft-empty still uses localized nothing-found stub."""
    monkeypatch.setenv("ADAPTIVE_GROUNDING_ENABLED", "false")
    from palatium_ai.core.config import get_settings

    get_settings.cache_clear()
    try:
        state = {
            "task_id": "t1",
            "user_text": "предложи темы",
            "response_locale": "ru-RU",
            "classification": IntentTaskResult(
                task_id="t1",
                agent_role="intent_classifier",
                status="success",
                confidence=0.9,
                output=IntentClassifierOutput(
                    task_kind="knowledge_request",
                    requires_mcp=True,
                    candidate_capabilities=("search",),
                    confidence=0.9,
                    reasoning="search",
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
