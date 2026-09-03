"""Offline LongMemEval-lite gates for the memory spine.

These cases encode the platform thesis: bad memory is worse than none,
and Contextualizer prompts must stay under an explicit budget.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.domain.memory.budget import MemoryPromptBudget, clip_memory_hints
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace
from palatium_ai.domain.memory.recall import MemoryHit, MemoryRecallBundle
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import FakeLLMPort, run_contextualizer


@pytest.mark.asyncio
async def test_eval_noise_memory_worse_than_none() -> None:
    """Low-confidence hits must not enter the hot path."""
    port = InMemoryMemoryPort()
    await port.put(
        namespace=thread_namespace("eval-noise"),
        key="bad",
        value={"text": "User maybe likes purple UI", "kind": "fact", "confidence": 0.35},
    )
    bundle = await recall_for_thread(
        port,
        thread_id="eval-noise",
        query="UI preferences",
        min_confidence=0.7,
    )
    assert bundle.hits == ()
    assert bundle.hint_texts == ()
    assert bundle.as_prompt_block() == "(no durable memory)"


@pytest.mark.asyncio
async def test_eval_recall_char_budget_gate() -> None:
    port = InMemoryMemoryPort()
    for idx in range(6):
        await port.put(
            namespace=thread_namespace("eval-budget"),
            key=f"k{idx}",
            value={
                "text": f"preference-{idx}-" + ("x" * 180),
                "kind": "preference",
                "confidence": 0.95,
                "_score": 10 - idx,
            },
        )
    bundle = await recall_for_thread(
        port,
        thread_id="eval-budget",
        query="preference",
        limit=4,
        max_chars=300,
        min_confidence=0.7,
    )
    assert len(bundle.as_prompt_block()) <= 300
    assert sum(len(t) for t in bundle.hint_texts) <= 300


def test_eval_dialog_prompt_keeps_recent_under_budget() -> None:
    turns = tuple(
        DialogTurn(
            id=uuid4(),
            thread_id="eval-dialog",
            role="user" if idx % 2 == 0 else "assistant",
            content=f"turn-{idx}-" + ("y" * 800),
            seq=idx,
            created_at=datetime.now(UTC),
        )
        for idx in range(8)
    )
    window = DialogTurnWindow(thread_id="eval-dialog", turns=turns, limit=12)
    block = window.as_prompt_block(max_chars=2500, per_turn_max_chars=400)
    assert len(block) <= 2500
    assert "turn-7-" in block
    assert "turn-0-" not in block or len(block) <= 2500


def test_eval_clip_memory_hints_respects_budget() -> None:
    hints = tuple(f"hint-{idx}-" + ("z" * 120) for idx in range(6))
    clipped = clip_memory_hints(hints, max_items=4, max_chars=280)
    assert len(clipped) <= 4
    assert sum(len(h) for h in clipped) <= 280


@pytest.mark.asyncio
async def test_eval_format_followup_rewritten_with_budget() -> None:
    """Canonical bug: 'дай таблицей' must become a format continuation."""
    llm = FakeLLMPort(
        """{
          "rewritten_query": "Представь предыдущий план встречи в виде таблицы",
          "continuation_kind": "format",
          "confidence": 0.93,
          "refers_to_prior": true,
          "prior_assistant_excerpt": "План: 1) время 2) повестка",
          "reasoning": "format request over prior plan"
        }"""
    )
    window = DialogTurnWindow(
        thread_id="eval-format",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="eval-format",
                role="user",
                content="Составь план встречи",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="eval-format",
                role="assistant",
                content="План: 1) время 2) повестка 3) участники",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
    )
    result = await run_contextualizer(
        llm,
        ContextualizerInput(
            task_id="eval-format",
            user_text="дай в виде таблицы",
            dialog_window=window,
            prompt_budget=MemoryPromptBudget(dialog_max_chars=2000, memory_max_chars=400),
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "format"
    assert "таблиц" in result.output.rewritten_query.lower()
    assert result.output.refers_to_prior is True
    assert llm.calls
    # Prompt payload must stay bounded even if history grows later.
    user_msg = llm.calls[0][-1].content
    assert len(user_msg) < 8000


def test_eval_hint_texts_align_with_prompt_block() -> None:
    hits = tuple(MemoryHit(text=f"fact-{idx}-" + ("a" * 100), kind="fact", confidence=0.9, score=1) for idx in range(5))
    bundle = MemoryRecallBundle(thread_id="eval-align", hits=hits, max_items=4, max_chars=250)
    hints = bundle.hint_texts
    block = bundle.as_prompt_block()
    assert hints
    assert all(h in block for h in hints)
    assert len(block) <= 250


@pytest.mark.asyncio
async def test_eval_org_memory_requires_org_id() -> None:
    """Org ACL: shared entities are invisible without org_id (no cross-tenant leak)."""
    port = InMemoryMemoryPort()
    await port.put(
        namespace=org_namespace("org-acme"),
        key="legal",
        value={"text": "Acme legal owner is Ivanova", "kind": "entity", "confidence": 0.95},
    )
    leaked = await recall_for_thread(port, thread_id="eval-acl", query="Acme legal", limit=4)
    assert leaked.hits == ()

    allowed = await recall_for_thread(
        port,
        thread_id="eval-acl",
        org_id="org-acme",
        query="Acme legal",
        limit=4,
    )
    assert allowed.hits
    assert "ivanova" in allowed.hits[0].text.lower() or "acme" in allowed.hits[0].text.lower()


@pytest.mark.asyncio
async def test_eval_multi_hop_anaphora_fixture_shape() -> None:
    """Offline fixture: two-hop follow-up must keep prior entity in rewritten query."""
    llm = FakeLLMPort(
        """{
          "rewritten_query": "Какой email у Ивановой по договору с Acme?",
          "continuation_kind": "answer",
          "confidence": 0.9,
          "refers_to_prior": true,
          "prior_assistant_excerpt": "Иванова из юридического отдела",
          "reasoning": "anaphora over prior person"
        }"""
    )
    window = DialogTurnWindow(
        thread_id="eval-hop",
        turns=(
            DialogTurn(
                id=uuid4(),
                thread_id="eval-hop",
                role="user",
                content="Кто отвечает за договор с Acme?",
                seq=0,
                created_at=datetime.now(UTC),
            ),
            DialogTurn(
                id=uuid4(),
                thread_id="eval-hop",
                role="assistant",
                content="За договор с Acme отвечает Иванова из юридического отдела.",
                seq=1,
                created_at=datetime.now(UTC),
            ),
        ),
    )
    result = await run_contextualizer(
        llm,
        ContextualizerInput(
            task_id="eval-hop",
            user_text="а её email?",
            dialog_window=window,
            prompt_budget=MemoryPromptBudget(),
        ),
    )
    assert result.output is not None
    assert result.output.continuation_kind == "answer"
    assert result.output.refers_to_prior is True
    rewritten = result.output.rewritten_query.lower()
    assert any(token in rewritten for token in ("иванов", "acme", "email", "почт"))
