"""Conversational Super Brain gates (SB5) — class scenarios, not phrase lists."""

from __future__ import annotations

from uuid import uuid4

import pytest

from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.domain.memory.scratchpad import ScratchpadSlot, SessionScratchpad
from palatium_ai.domain.memory.turns import (
    DialogTurn,
    DialogTurnWindow,
    attachment_ids_payload,
)
from palatium_ai.domain.policies.attachment_stickiness import AttachmentStickinessPolicy
from palatium_ai.domain.policies.formatter_memory_merge import FormatterMemoryMergePolicy
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort


def test_sb5_sticky_poison_no_entry_restore() -> None:
    """Upload A then social/creative follow-up must not auto-fence sticky pending."""
    pending = uuid4()
    decision = AttachmentStickinessPolicy.decide_entry(
        explicit_ids=None,
        pending_ids=(pending,),
    )
    assert decision.restore_ids == ()
    assert decision.reason == "skip_sticky_restore"
    clear = AttachmentStickinessPolicy.decide_rehydrate(
        continuation_kind="new_topic",
        refers_to_prior=False,
        has_turn_attachments=False,
        dialog=None,
        prior_context=None,
        trust_prior_for_workers=False,
    )
    assert clear.clear_pending is True


def test_sb5_underspec_followup_after_pdf_clears_sticky_no_format_rehydrate() -> None:
    """PDF summary → underspec follow-up: Continuity demotes false format; SB2 clears pending."""
    from palatium_ai.domain.agents.intent import IntentClassifierOutput
    from palatium_ai.domain.memory.contextualizer import ContextualizerOutput
    from palatium_ai.domain.policies import ContinuityPolicy

    doc_id = uuid4()
    window = DialogTurnWindow(
        thread_id="thread-sb5-false-format",
        turns=(
            DialogTurn(
                thread_id="thread-sb5-false-format",
                role="user",
                content="подготовь ответ по письму",
                payload=attachment_ids_payload((doc_id,)),
                seq=0,
            ),
            DialogTurn(
                thread_id="thread-sb5-false-format",
                role="assistant",
                content="Основание: письмо ООО… Параметры мероприятия…",
                seq=1,
            ),
        ),
    )
    ctx = ContextualizerOutput(
        rewritten_query="Переформатируй сводку письма",
        continuation_kind="format",
        confidence=0.9,
        refers_to_prior=True,
        prior_assistant_excerpt="Основание: письмо ООО…",
        reasoning="false format on open-slot ask",
    )
    raw = IntentClassifierOutput(
        task_kind="clarification_needed",
        requires_mcp=False,
        underspecification_kind="open_text",
        candidate_capabilities=(),
        confidence=0.9,
        reasoning="missing topic",
    )
    routing = ContinuityPolicy.resolve(contextualizer=ctx, dialog=window, raw_intent=raw)
    assert routing.task_kind == "clarification_needed"
    assert routing.trust_prior_for_workers is False
    rehydrate = AttachmentStickinessPolicy.decide_rehydrate(
        continuation_kind=routing.continuation_kind,
        refers_to_prior=False,
        has_turn_attachments=False,
        dialog=window,
        prior_context=routing.prior_context,
        trust_prior_for_workers=routing.trust_prior_for_workers,
    )
    assert rehydrate.clear_pending is True
    assert rehydrate.attachment_ids == ()


def test_sb5_doc_format_rehydrates_prior_attachment_not_latest_sticky() -> None:
    """Format ask for earlier doc must select that turn's attachment_ids, not later webp."""
    doc_id = uuid4()
    webp_id = uuid4()
    window = DialogTurnWindow(
        thread_id="thread-sb5",
        turns=(
            DialogTurn(
                thread_id="thread-sb5",
                role="user",
                content="напиши ответ на обращение",
                payload=attachment_ids_payload((doc_id,)),
                seq=0,
            ),
            DialogTurn(
                thread_id="thread-sb5",
                role="assistant",
                content="Уважаемая Татьяна Васильевна! По вопросу образования…",
                seq=1,
            ),
            DialogTurn(
                thread_id="thread-sb5",
                role="user",
                content="цены на скрине",
                payload=attachment_ids_payload((webp_id,)),
                seq=2,
            ),
            DialogTurn(
                thread_id="thread-sb5",
                role="assistant",
                content="Иван-чай оптом 1500",
                seq=3,
            ),
        ),
    )
    decision = AttachmentStickinessPolicy.decide_rehydrate(
        continuation_kind="format",
        refers_to_prior=True,
        has_turn_attachments=False,
        dialog=window,
        prior_context="Уважаемая Татьяна Васильевна! По вопросу образования…",
        trust_prior_for_workers=True,
    )
    assert decision.attachment_ids == (doc_id,)
    assert webp_id not in decision.attachment_ids


def test_sb5_identity_and_task_hints_coexist_with_source() -> None:
    """Name pin + worker source: Formatter still gets identity slice."""
    decision = FormatterMemoryMergePolicy.decide(
        memory_hints=("User name is Gennadiy",),
        has_source_content=True,
        hit_kinds=("preference",),
    )
    assert decision.hints == ("User name is Gennadiy",)


@pytest.mark.asyncio()
async def test_sb5_l4_select_includes_graph_hint() -> None:
    """Seeded MemoryFact appears in recall bundle when policy allows."""
    graph = InMemoryGraphWritePort()
    await graph.upsert_fact(
        GraphFactUpsert(
            user_id="u-sb5",
            entry_key="pref-name",
            text="User prefers formal replies",
            kind="preference",
            importance=0.9,
            confidence=0.95,
            thread_id="t-sb5",
        )
    )
    pad = SessionScratchpad(
        thread_id="t-sb5",
        slots=(
            ScratchpadSlot(
                key="pref-name",
                kind="preference",
                text="short name pin: Gennadiy",
                confidence=1.0,
            ),
        ),
    )
    bundle = await recall_for_thread(
        None,
        thread_id="t-sb5",
        query="how should you address me",
        user_id="u-sb5",
        scratchpad=pad,
        graph_write=graph,
        min_confidence=0.7,
    )

    # Scratchpad-only path when memory_port is None — graph still fused when port None?
    # recall_for_thread returns early without graph when memory_port is None.
    # Re-run with a no-op medium port so L4 fusion runs.
    class _EmptyMedium:
        async def search(self, *, namespace: tuple[str, ...], query: str, limit: int = 8) -> list[dict[str, object]]:
            _ = (namespace, query, limit)
            return []

        async def bump_access(self, *, namespace: tuple[str, ...], key: str) -> None:
            _ = (namespace, key)

    bundle = await recall_for_thread(
        _EmptyMedium(),  # type: ignore[arg-type]
        thread_id="t-sb5",
        query="how should you address me",
        user_id="u-sb5",
        scratchpad=pad,
        graph_write=graph,
        min_confidence=0.7,
    )
    texts = " ".join(bundle.hint_texts)
    assert "Gennadiy" in texts or "formal" in texts.lower()
    assert any(h.source == "graph" for h in bundle.hits) or any("formal" in h.text.lower() for h in bundle.hits)
