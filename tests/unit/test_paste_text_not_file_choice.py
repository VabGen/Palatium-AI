"""Regression: pasted chat-text analysis must not mint a thread-file choice card.

Live UX (2026-11-17): user pasted EV/paraphrase/extract tasks into a dialog that
already held two «Договор_оказания_услуг*.docx» files. Weak leading-title
«договор» matched both siblings → several_names_in_turn_text → Continuity
promoted thread_file → HITL «Выберите, какой именно нужно перечитать» — and
repeated after the user said the ask was about chat text, not the contracts.
"""

from __future__ import annotations

from uuid import uuid4

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.policies.continuity import ContinuityPolicy
from palatium_ai.domain.policies.file_reference import FileRefCandidate, FileReferencePolicy

_PASTE_ASK = (
    "1. Проанализируй следующий текст и выдели 5 ключевых тезисов: "
    "Глобальный рынок электромобилей растёт…\n"
    "2. Перефразируй в официально-деловом стиле: Система сегодня тормозит…\n"
    "3. Извлеки даты, имена и названия компаний: "
    "12 апреля 2023 года компания «ТехноСфера» подписала договор с ООО «Инновации»…"
)

_CORRECTION = "причем тут договор я просил проанализировать текст который передал в чат"


def _candidate(name: str) -> FileRefCandidate:
    return FileRefCandidate(attachment_id=uuid4(), filename=name, search_text="")


def test_two_contract_siblings_do_not_promote_on_paste_prose_dogovor() -> None:
    """Shared lead «договор» in prose among Договор_*.docx is not a named re-read."""
    first = _candidate("Договор оказания услуг.docx")
    second = _candidate("Договор оказания услуг_2.docx")
    resolution = FileReferencePolicy.resolve([first, second], hint_text=_PASTE_ASK)
    assert resolution.status == "ambiguous"
    assert resolution.reason == "several_thread_files"
    assert FileReferencePolicy.promotes_thread_file_reread(resolution) is False


def test_user_correction_mentioning_dogovor_still_does_not_promote() -> None:
    first = _candidate("Договор оказания услуг.docx")
    second = _candidate("Договор оказания услуг_2.docx")
    resolution = FileReferencePolicy.resolve([first, second], hint_text=_CORRECTION)
    assert FileReferencePolicy.promotes_thread_file_reread(resolution) is False


def test_continuity_demotes_intent_thread_file_when_focus_none() -> None:
    """Intent focus=none → Continuity must not keep a bare storage re-read."""
    intent = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        candidate_capabilities=("retrieve",),
        confidence=0.9,
        reasoning="paste text analysis",
        file_reference="thread_file",
        attachment_scope="single",
        attachment_focus="none",
    )
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=None,
        raw_intent=intent,
        has_turn_attachments=False,
        user_text=_PASTE_ASK,
        thread_file_named=False,
    )
    assert effective.file_reference == "none"


def test_continuity_demotes_intent_single_over_paste_without_file_cue() -> None:
    """History-blind Intent ``single`` must not interrupt a chat-text paste."""
    intent = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        candidate_capabilities=("retrieve",),
        confidence=0.9,
        reasoning="history-blind thread files",
        file_reference="thread_file",
        attachment_scope="single",
        attachment_focus="current_uploads",
    )
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=None,
        raw_intent=intent,
        has_turn_attachments=False,
        user_text=_PASTE_ASK,
        thread_file_named=False,
    )
    assert effective.file_reference == "none"


def test_continuity_demotes_correction_that_only_mentions_dogovor() -> None:
    """User rejection of a false file card must not re-mint it via Intent single."""
    intent = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=True,
        candidate_capabilities=("retrieve",),
        confidence=0.85,
        reasoning="mentions договор",
        file_reference="thread_file",
        attachment_scope="single",
        attachment_focus="current_uploads",
    )
    effective = ContinuityPolicy.resolve(
        contextualizer=None,
        dialog=None,
        raw_intent=intent,
        has_turn_attachments=False,
        user_text=_CORRECTION,
        thread_file_named=False,
    )
    assert effective.file_reference == "none"


def test_scan_siblings_still_ambiguous_on_shared_single_token_lead() -> None:
    """«открой скан» among Скан 1/2 must still mint a card (digit-sibling family)."""
    scan1 = _candidate("Скан 1 _Приложение.pdf")
    scan2 = _candidate("Скан 2 _Приложение.pdf")
    resolution = FileReferencePolicy.resolve([scan1, scan2], hint_text="открой скан ещё раз")
    assert resolution.status == "ambiguous"
    assert resolution.reason == "several_names_in_turn_text"
    assert FileReferencePolicy.promotes_thread_file_reread(resolution) is True


def test_paste_over_zayavka_and_webp_does_not_promote() -> None:
    """Screenshot 2026-11-17: EV/paraphrase/extract paste with ht_1-5 + Заявка PDF."""
    resolution = FileReferencePolicy.resolve(
        [_candidate("ht_1-5.webp"), _candidate("Заявка_сведения_СЭД.pdf")],
        hint_text=_PASTE_ASK,
    )
    assert resolution.reason == "several_thread_files"
    assert FileReferencePolicy.promotes_thread_file_reread(resolution) is False
    assert FileReferencePolicy.ask_engages_file_identity(_PASTE_ASK) is False


def test_self_contained_paste_worker_prior_drops_stale_excerpt() -> None:
    """Belt: leftover prior_context must not reach workers when trust is false.

    The dialog copy stays available to Critic/Formatter (context circulation); the
    trust axis only silences the worker path, where a stale refusal would be read as
    ``previous_answer`` to a self-contained paste.
    """
    from typing import cast

    from palatium_ai.application.orchestration.selectors import (
        resolved_prior_assistant_content,
        resolved_worker_prior_assistant_content,
    )
    from palatium_ai.application.orchestration.state import AgentGraphState
    from palatium_ai.domain.policies.continuity import EffectiveRoutingIntent

    state = cast(
        "AgentGraphState",
        {
            "task_id": "t-paste",
            "user_text": _PASTE_ASK,
            "routing_intent": EffectiveRoutingIntent(
                task_kind="knowledge_request",
                continuation_kind="answer",
                prior_context=("В приложенном файле «Заявка…Госархив» отсутствует текст о ТехноСфере…"),
                trust_prior_for_workers=False,
                grounding="none",
                grounding_reason="continuity→none (self-contained)",
                reasoning="belt-and-suspenders: Continuity should have cleared prior",
            ),
        },
    )
    assert resolved_worker_prior_assistant_content(state) is None
    assert resolved_prior_assistant_content(state) is not None
