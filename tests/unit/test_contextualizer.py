"""Unit tests for Contextualizer + dialog window pass-through."""

from __future__ import annotations

import json

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.agents.context_enricher import CONTEXTUALIZER_CONFIG, ContextualizerAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.orchestration.agent_bridge import (
    contextualizer_output_to_task_result,
    contextualizer_to_agent_input,
)
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from tests.conftest import FakeLLMPort


async def _contextualize(llm: FakeLLMPort, task_input: ContextualizerInput):
    harness = Harness(llm=llm)
    agent = ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG)
    agent_input = contextualizer_to_agent_input(
        task_input,
        trace_id="trace-1",
        thread_id=task_input.dialog_window.thread_id,
    )
    output = await harness.execute_with_guardrails(agent, agent_input)
    return contextualizer_output_to_task_result(
        output,
        task_id=task_input.task_id,
        agent_role=agent.config.role,
    )


@pytest.mark.asyncio()
async def test_contextualizer_passthrough_without_history() -> None:
    llm = FakeLLMPort("should-not-be-called")
    result = await _contextualize(
        llm,
        ContextualizerInput(
            task_id="t1",
            user_text="привет",
            dialog_window=DialogTurnWindow(thread_id="th1", turns=()),
        ),
    )
    assert result.status == "success"
    assert result.output is not None
    assert result.output.rewritten_query == "привет"
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0


@pytest.mark.asyncio()
async def test_contextualizer_rewrites_format_followup() -> None:
    llm = FakeLLMPort(
        """{
          "rewritten_query": "Представь предыдущий план встречи в виде таблицы",
          "continuation_kind": "format",
          "confidence": 0.92,
          "refers_to_prior": true,
          "prior_assistant_excerpt": "План встречи на завтра",
          "reasoning": "User asked to tabulate prior answer"
        }"""
    )
    window = DialogTurnWindow(
        thread_id="th2",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th2",
                role="user",
                content="Составь план встречи на завтра",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="th2",
                role="assistant",
                content="План встречи на завтра\n1. Время…",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
    )
    result = await _contextualize(
        llm,
        ContextualizerInput(task_id="t2", user_text="дай в виде таблицы", dialog_window=window),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "format"
    assert "таблиц" in result.output.rewritten_query.lower()
    assert result.output.refers_to_prior is True


@pytest.mark.asyncio()
async def test_contextualizer_uses_memory_hints_without_turns() -> None:
    """Memory hints alone do not require rewrite when there is no assistant prior."""
    llm = FakeLLMPort("should-not-be-called")
    result = await _contextualize(
        llm,
        ContextualizerInput(
            task_id="t3",
            user_text="Составь план встречи",
            dialog_window=DialogTurnWindow(thread_id="th3", turns=()),
            memory_hints=("User prefers meeting plans as tables",),
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0


@pytest.mark.asyncio()
async def test_contextualizer_skips_llm_for_social_with_prior() -> None:
    llm = FakeLLMPort("should-not-be-called")
    window = DialogTurnWindow(
        thread_id="th-social",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th-social",
                role="user",
                content="привет",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="th-social",
                role="assistant",
                content="Привет!",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
    )
    result = await _contextualize(
        llm,
        ContextualizerInput(
            task_id="t-social",
            user_text="как дела",
            dialog_window=window,
            task_kind="social_conversation",
            requires_mcp=False,
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0


@pytest.mark.asyncio()
async def test_contextualizer_passthrough_user_only_history() -> None:
    """First turn in thread: user message stored but no assistant reply yet."""
    llm = FakeLLMPort("should-not-be-called")
    window = DialogTurnWindow(
        thread_id="th4",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th4",
                role="user",
                content="привет",
                seq=0,
                created_at=datetime.now(UTC),
            ),
        ),
    )
    result = await _contextualize(
        llm,
        ContextualizerInput(task_id="t4", user_text="привет", dialog_window=window),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0


@pytest.mark.asyncio()
async def test_contextualizer_gets_turn_attachment_flag() -> None:
    """Uploads in the turn must reach the rewrite prompt, else "files" looks missing.

    Live symptom: two PDFs attached, Contextualizer returned clarify with
    «no files have been provided or mentioned in the dialog history», the Formatter
    then asked the user to upload a file that was already there (055).
    """
    llm = FakeLLMPort(
        """{
          "rewritten_query": "Сравни оба приложенных файла и покажи отличия",
          "continuation_kind": "answer",
          "confidence": 0.9,
          "refers_to_prior": false,
          "prior_assistant_excerpt": null,
          "reasoning": "referent is the turn upload, not the dialog"
        }"""
    )
    window = DialogTurnWindow(
        thread_id="th-att",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th-att",
                role="user",
                content="привет",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="th-att",
                role="assistant",
                content="Привет! Как дела?",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
    )
    harness = Harness(llm=llm)
    agent = ContextualizerAgent(harness, CONTEXTUALIZER_CONFIG)
    assert "has_attachment_context" in agent.get_required_context_keys()

    await _contextualize(
        llm,
        ContextualizerInput(
            task_id="t-att",
            user_text="сравни файлы и покажи все отличия в табличном виде",
            dialog_window=window,
            task_kind="response_formatting",
            has_attachment_context=True,
        ),
    )

    assert llm.calls, "prior-dependent kind must consult the LLM"
    payload = json.loads(llm.calls[0][1].content)
    assert payload["has_attachment_context"] is True


@pytest.mark.asyncio()
async def test_contextualizer_payload_flag_false_without_attachments() -> None:
    llm = FakeLLMPort(
        """{
          "rewritten_query": "дай план в виде таблицы",
          "continuation_kind": "format",
          "confidence": 0.9,
          "refers_to_prior": true,
          "prior_assistant_excerpt": "План встречи на завтра",
          "reasoning": "tabulate prior answer"
        }"""
    )
    window = DialogTurnWindow(
        thread_id="th-noatt",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="th-noatt",
                role="assistant",
                content="План встречи на завтра",
                seq=0,
                created_at=datetime.now(UTC),
            ),
        ),
    )
    await _contextualize(
        llm,
        ContextualizerInput(
            task_id="t-noatt",
            user_text="дай в виде таблицы",
            dialog_window=window,
            task_kind="response_formatting",
        ),
    )
    payload = json.loads(llm.calls[0][1].content)
    assert payload["has_attachment_context"] is False
