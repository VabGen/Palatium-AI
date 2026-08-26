"""Unit tests for Contextualizer + dialog window pass-through."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.agents.contextualizer_agent import ContextualizerAgent
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from tests.conftest import FakeLLMPort


@pytest.mark.asyncio
async def test_contextualizer_passthrough_without_history() -> None:
    llm = FakeLLMPort("should-not-be-called")
    agent = ContextualizerAgent(llm)
    result = await agent.execute(
        ContextualizerInput(
            task_id="t1",
            user_text="привет",
            dialog_window=DialogTurnWindow(thread_id="th1", turns=()),
        ),
        AgentContext(thread_id="th1"),
    )
    assert result.status == "success"
    assert result.output is not None
    assert result.output.rewritten_query == "привет"
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0


@pytest.mark.asyncio
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
    agent = ContextualizerAgent(llm)
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
    result = await agent.execute(
        ContextualizerInput(task_id="t2", user_text="дай в виде таблицы", dialog_window=window),
        AgentContext(thread_id="th2"),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "format"
    assert "таблиц" in result.output.rewritten_query.lower()
    assert result.output.refers_to_prior is True


@pytest.mark.asyncio
async def test_contextualizer_uses_memory_hints_without_turns() -> None:
    """Memory hints alone do not require rewrite when there is no assistant prior."""
    llm = FakeLLMPort("should-not-be-called")
    agent = ContextualizerAgent(llm)
    result = await agent.execute(
        ContextualizerInput(
            task_id="t3",
            user_text="Составь план встречи",
            dialog_window=DialogTurnWindow(thread_id="th3", turns=()),
            memory_hints=("User prefers meeting plans as tables",),
        ),
        AgentContext(thread_id="th3"),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_contextualizer_skips_llm_for_social_with_prior() -> None:
    llm = FakeLLMPort("should-not-be-called")
    agent = ContextualizerAgent(llm)
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
    result = await agent.execute(
        ContextualizerInput(
            task_id="t-social",
            user_text="как дела",
            dialog_window=window,
            task_kind="social_conversation",
            requires_mcp=False,
        ),
        AgentContext(thread_id="th-social"),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0


@pytest.mark.asyncio
async def test_contextualizer_passthrough_user_only_history() -> None:
    """First turn in thread: user message stored but no assistant reply yet."""
    llm = FakeLLMPort("should-not-be-called")
    agent = ContextualizerAgent(llm)
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
    result = await agent.execute(
        ContextualizerInput(task_id="t4", user_text="привет", dialog_window=window),
        AgentContext(thread_id="th4"),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "new_topic"
    assert len(llm.calls) == 0
