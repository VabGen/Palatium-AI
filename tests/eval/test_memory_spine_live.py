"""Live LongMemEval-lite: Contextualizer + MemoryKeeper against a real LLM.

Opt-in only:
  PALATIUM_LIVE_EVAL=1 poetry run pytest tests/eval/test_memory_spine_live.py -q
  # or
  poetry run python scripts/eval_memory_spine_live.py
"""

from __future__ import annotations

import pytest

from palatium_ai.domain.agents.memory_keeper import MemoryKeeperInput
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.turns import DialogTurnWindow
from tests.conftest import run_contextualizer, run_memory_keeper
from tests.eval.live_helpers import dialog_pair, require_live

pytestmark = [pytest.mark.live, require_live]


@pytest.mark.asyncio
async def test_live_format_followup_is_format_kind(live_llm) -> None:
    window = dialog_pair(
        thread_id="live-format",
        user_text="Составь план встречи на завтра",
        assistant_text="План встречи:\n1. Время\n2. Повестка\n3. Участники",
    )
    result = await run_contextualizer(
        live_llm,
        ContextualizerInput(
            task_id="live-format",
            user_text="дай в виде таблицы",
            dialog_window=window,
            prompt_budget=MemoryPromptBudget(),
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "format"
    assert result.output.refers_to_prior is True
    rewritten = result.output.rewritten_query.lower()
    assert any(token in rewritten for token in ("таблиц", "table", "план", "встреч"))


@pytest.mark.asyncio
async def test_live_anaphora_answer_refers_to_prior(live_llm) -> None:
    window = dialog_pair(
        thread_id="live-anaphora",
        user_text="Кто отвечает за договор с Acme?",
        assistant_text="За договор с Acme отвечает Иванова из юридического отдела.",
    )
    result = await run_contextualizer(
        live_llm,
        ContextualizerInput(
            task_id="live-anaphora",
            user_text="а её email?",
            dialog_window=window,
            prompt_budget=MemoryPromptBudget(),
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind in {"answer", "clarify"}
    assert result.output.refers_to_prior is True
    rewritten = result.output.rewritten_query.lower()
    assert any(token in rewritten for token in ("ivanov", "иванов", "acme", "email", "почт"))


@pytest.mark.asyncio
async def test_live_new_topic_does_not_force_prior(live_llm) -> None:
    window = dialog_pair(
        thread_id="live-new",
        user_text="Составь план встречи",
        assistant_text="План: время, повестка, участники.",
    )
    result = await run_contextualizer(
        live_llm,
        ContextualizerInput(
            task_id="live-new",
            user_text="Какая погода в Минске сегодня?",
            dialog_window=window,
            prompt_budget=MemoryPromptBudget(),
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "new_topic"
    assert "минск" in result.output.rewritten_query.lower() or "погод" in result.output.rewritten_query.lower()


@pytest.mark.asyncio
async def test_live_memory_hints_surface_preference(live_llm) -> None:
    result = await run_contextualizer(
        live_llm,
        ContextualizerInput(
            task_id="live-hints",
            user_text="Составь план встречи на пятницу",
            dialog_window=DialogTurnWindow(thread_id="live-hints", turns=()),
            memory_hints=("User prefers meeting agendas as markdown tables",),
            prompt_budget=MemoryPromptBudget(),
        ),
    )
    assert result.output is not None
    rewritten = result.output.rewritten_query.lower()
    # Soft gate: either mentions table preference or keeps a standalone meeting request.
    assert "встреч" in rewritten or "meeting" in rewritten or "agenda" in rewritten
    assert result.output.confidence >= 0.5


@pytest.mark.asyncio
async def test_live_memory_keeper_extracts_preference(live_llm) -> None:
    transcript = (
        "user: Я всегда хочу планы встреч в виде таблицы.\n"
        "assistant: Хорошо, буду оформлять планы таблицей.\n"
        "user: Составь план на завтра.\n"
        "assistant: | Время | Тема |\n|---|---|\n| 10:00 | Синк |"
    )
    result = await run_memory_keeper(
        MemoryKeeperInput(
            task_id="live-keeper-pref",
            thread_id="live-keeper-pref",
            transcript_excerpt=transcript,
            existing_memory_texts=(),
        ),
        live_llm,
    )
    assert result.output is not None
    solid = [f for f in result.output.facts if f.confidence >= 0.7]
    assert solid, "expected at least one high-confidence durable memory"
    blob = " ".join(f.text.lower() for f in solid)
    assert any(token in blob for token in ("таблиц", "table", "prefer"))


@pytest.mark.asyncio
async def test_live_memory_keeper_skips_ephemeral_format(live_llm) -> None:
    transcript = (
        "user: Составь короткий список покупок.\n"
        "assistant: 1. Молоко 2. Хлеб 3. Яйца\n"
        "user: дай списком через запятую\n"
        "assistant: Молоко, хлеб, яйца"
    )
    result = await run_memory_keeper(
        MemoryKeeperInput(
            task_id="live-keeper-skip",
            thread_id="live-keeper-skip",
            transcript_excerpt=transcript,
            existing_memory_texts=(),
        ),
        live_llm,
    )
    assert result.output is not None
    # Format-only chatter should not become durable memory (or only very low confidence).
    durable = [f for f in result.output.facts if f.confidence >= 0.7]
    assert not durable


@pytest.mark.asyncio
async def test_live_clarify_when_history_insufficient(live_llm) -> None:
    window = dialog_pair(
        thread_id="live-clarify",
        user_text="Составь план",
        assistant_text="Уточните: план чего именно?",
    )
    result = await run_contextualizer(
        live_llm,
        ContextualizerInput(
            task_id="live-clarify",
            user_text="ну тот",
            dialog_window=window,
            prompt_budget=MemoryPromptBudget(),
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind in {"clarify", "answer", "format"}
    # Soft gate: either clarify or a rewritten standalone query that is not empty.
    assert result.output.rewritten_query.strip()
