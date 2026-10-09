"""CONTEXTUALIZER_DEBUG_PAYLOAD logs gate + LLM payload only when enabled."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.orchestration.agent_bridge import contextualizer_to_agent_input
from palatium_ai.core.config.contextualizer import ContextualizerConfig
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from tests.conftest import FakeLLMPort


def _settings(*, debug: bool) -> SimpleNamespace:
    return SimpleNamespace(contextualizer=ContextualizerConfig(debug_payload=debug))


def _window() -> DialogTurnWindow:
    thread_id = "th-debug"
    return DialogTurnWindow(
        thread_id=thread_id,
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role="user",
                content="Вот текст обращения",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role="assistant",
                content="Обращение гражданина Иванова И.И.",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
    )


async def _run(*, debug: bool) -> MagicMock:
    llm = FakeLLMPort(
        """{
          "rewritten_query": "Составь ответ на обращение",
          "continuation_kind": "answer",
          "confidence": 0.9,
          "refers_to_prior": true,
          "prior_assistant_excerpt": "Обращение гражданина Иванова И.И.",
          "reasoning": "draft reply"
        }"""
    )
    harness = Harness(llm=llm)
    agent = ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG)
    agent_input = contextualizer_to_agent_input(
        ContextualizerInput(
            task_id="t-debug",
            user_text="составь ответ на это обращение",
            dialog_window=_window(),
            task_kind="knowledge_request",
        ),
        trace_id="trace-debug",
        thread_id="th-debug",
    )
    log_mock = MagicMock()
    with (
        patch("palatium_ai.core.config.get_settings", return_value=_settings(debug=debug)),
        patch(
            "palatium_ai.application.agents.context_enricher.continuation.agent.logger",
            log_mock,
        ),
    ):
        await harness.execute_with_guardrails(agent, agent_input)
    return log_mock


@pytest.mark.asyncio()
async def test_debug_payload_silent_when_flag_off() -> None:
    log_mock = await _run(debug=False)
    assert not any(call.args and call.args[0] == "contextualizer.debug_payload" for call in log_mock.info.call_args_list)


@pytest.mark.asyncio()
async def test_debug_payload_logs_request_and_response_when_flag_on() -> None:
    log_mock = await _run(debug=True)
    events = [call.args[0] for call in log_mock.info.call_args_list if call.args]
    assert events.count("contextualizer.debug_payload") == 2
    kwargs_list = [call.kwargs for call in log_mock.info.call_args_list if call.args and call.args[0] == "contextualizer.debug_payload"]
    phases = {item["phase"] for item in kwargs_list}
    assert phases == {"llm_request", "llm_response"}
    request = next(item for item in kwargs_list if item["phase"] == "llm_request")
    assert request["invoke_llm"] is True
    assert isinstance(request["user_payload"], dict)
    assert request["user_payload"]["user_text"] == "составь ответ на это обращение"
    response = next(item for item in kwargs_list if item["phase"] == "llm_response")
    assert response["continuation_kind"] == "answer"
    assert response["refers_to_prior"] is True
