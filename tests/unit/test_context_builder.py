"""ContextBuilder.compact + goal/plan persist (065/060)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.application.services.context_builder import ContextBuilder
from palatium_ai.domain.memory.compact import CompactRequest
from palatium_ai.domain.memory.namespaces import thread_namespace, user_namespace
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.compact import COMPACT_THRESHOLD_RATIO, CompactPolicy
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


@pytest.mark.asyncio
async def test_build_returns_empty_for_no_keys() -> None:
    builder = ContextBuilder()
    assert await builder.build([], thread_id="t1") == {}


@pytest.mark.asyncio
async def test_build_loads_history_from_dialog_store() -> None:
    dialog_store = AsyncMock()
    dialog_store.list_recent_turns.return_value = DialogTurnWindow(
        thread_id="t1",
        turns=(
            DialogTurn(thread_id="t1", role="user", content="hello"),
            DialogTurn(thread_id="t1", role="assistant", content="hi there"),
        ),
    )
    builder = ContextBuilder(dialog_store=dialog_store)
    context = await builder.build(["history"], thread_id="t1")
    assert context["history"] == "user: hello\nassistant: hi there"
    dialog_store.list_recent_turns.assert_awaited_once_with(thread_id="t1", limit=12)


@pytest.mark.asyncio
async def test_build_raises_for_unknown_key() -> None:
    builder = ContextBuilder()
    with pytest.raises(KeyError, match="Unknown or unavailable context key"):
        await builder.build(["not_a_real_key"], thread_id="t1")


@pytest.mark.asyncio
async def test_build_loads_long_term_memory_when_user_present() -> None:
    memory_port = AsyncMock()
    memory_port.search.return_value = [{"text": "prefers concise answers"}]
    builder = ContextBuilder(memory_port=memory_port)
    context = await builder.build(
        ["long_term_memory"],
        thread_id="t1",
        user_id="alice",
        instruction="summarize",
    )
    assert context["long_term_memory"] == "prefers concise answers"
    memory_port.search.assert_awaited_once()


def test_compact_policy_threshold_uses_registry_ratio() -> None:
    limit = CompactPolicy.limit_tokens(model_tier="nano")
    assert CompactPolicy.threshold_tokens(model_tier="nano") == int(limit * COMPACT_THRESHOLD_RATIO)
    assert CompactPolicy.needs_compact(tokens=limit, model_tier="nano") is True
    assert CompactPolicy.needs_compact(tokens=1, model_tier="nano") is False


def test_extractive_summary_is_marked_not_silent() -> None:
    body = ("user: ask\nassistant: " + ("y" * 8000) + "\n") * 3
    out = CompactPolicy.extractive_summary(body, tokens_before=9000)
    assert "context_compacted" in out
    assert "method=extractive" in out
    assert "middle omitted by compact" in out


@pytest.mark.asyncio
async def test_compact_noop_under_threshold() -> None:
    port = InMemoryMemoryPort()
    builder = ContextBuilder(memory_port=port)
    result = await builder.compact(
        CompactRequest(
            dialog="user: hi\nassistant: hello",
            goal="ship compact",
            plan="step 1",
            model_tier="nano",
            thread_id="t-small",
            user_id="u1",
        )
    )
    assert result.did_compact is False
    assert result.method == "none"
    assert result.tokens_before == result.tokens_after
    assert await port.get(namespace=thread_namespace("t-small"), key="compact_preserve:goal") is None


@pytest.mark.asyncio
async def test_compact_persists_goal_plan_and_marks_dialog() -> None:
    port = InMemoryMemoryPort()
    builder = ContextBuilder(memory_port=port)
    # ~27k+ tokens on nano (32k limit, 80% ≈ 25.6k) forces compact without LLM summarizer.
    huge_dialog = "user: note\nassistant: " + ("x" * 110_000)
    result = await builder.compact(
        CompactRequest(
            dialog=huge_dialog,
            goal="Finish duck recipe thread",
            plan="1) recall preference 2) answer",
            last_results="prior code sample delivered",
            model_tier="nano",
            thread_id="t-huge",
            user_id="alice",
        )
    )
    assert result.did_compact is True
    assert result.method == "extractive"
    assert "context_compacted" in result.dialog
    assert result.tokens_after < result.tokens_before
    assert result.goal == "Finish duck recipe thread"
    assert "goal" in result.persisted_keys
    assert "plan" in result.persisted_keys
    assert "last_results" in result.persisted_keys

    stored_goal = await port.get(namespace=thread_namespace("t-huge"), key="compact_preserve:goal")
    assert stored_goal is not None
    assert "duck" in str(stored_goal.get("text", "")).lower()
    user_goal = await port.get(namespace=user_namespace("alice"), key="compact_preserve:goal")
    assert user_goal is not None

    rebuilt = await builder.build(["goal", "plan", "last_results"], thread_id="t-huge", user_id="alice")
    assert "duck" in rebuilt["goal"].lower()
    assert "recall" in rebuilt["plan"].lower()
    assert "code" in rebuilt["last_results"].lower()


@pytest.mark.asyncio
async def test_compact_uses_llm_summarizer_when_provided() -> None:
    port = InMemoryMemoryPort()

    class _FakeSummarizer:
        async def summarize_dialog(self, dialog: str) -> str:
            assert "x" * 100 in dialog
            return "Summary: long thread about search code and dinner."

    builder = ContextBuilder(memory_port=port, summarizer=_FakeSummarizer())
    huge_dialog = "user: note\nassistant: " + ("x" * 110_000)
    result = await builder.compact(
        CompactRequest(
            dialog=huge_dialog,
            goal="g",
            plan="p",
            model_tier="nano",
            thread_id="t-llm",
        )
    )
    assert result.did_compact is True
    assert result.method == "llm"
    assert "Summary: long thread" in result.dialog
    assert "method=llm" in result.dialog
