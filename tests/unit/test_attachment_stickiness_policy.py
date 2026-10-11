"""Unit tests for AttachmentStickinessPolicy (Super Brain SB1/SB2)."""

from __future__ import annotations

from uuid import uuid4

from palatium_ai.domain.memory.turns import (
    DialogTurn,
    DialogTurnWindow,
    attachment_ids_payload,
)
from palatium_ai.domain.policies.attachment_stickiness import AttachmentStickinessPolicy


def test_entry_explicit_upload_restores() -> None:
    aid = uuid4()
    decision = AttachmentStickinessPolicy.decide_entry(
        explicit_ids=(aid,),
        pending_ids=(uuid4(),),
    )
    assert decision.restore_ids == (aid,)
    assert decision.reason == "explicit_upload"
    assert decision.clear_pending is False


def test_entry_skips_sticky_pending() -> None:
    pending = uuid4()
    decision = AttachmentStickinessPolicy.decide_entry(
        explicit_ids=None,
        pending_ids=(pending,),
    )
    assert decision.restore_ids == ()
    assert decision.reason == "skip_sticky_restore"
    assert decision.clear_pending is False


def test_rehydrate_clears_pending_on_new_topic() -> None:
    decision = AttachmentStickinessPolicy.decide_rehydrate(
        continuation_kind="new_topic",
        refers_to_prior=False,
        has_turn_attachments=False,
        dialog=None,
        prior_context=None,
        trust_prior_for_workers=False,
    )
    assert decision.clear_pending is True
    assert decision.attachment_ids == ()


def test_rehydrate_clears_pending_when_format_not_trusted() -> None:
    """False format after Continuity demote must not re-fence sticky PDF."""
    doc_id = uuid4()
    window = DialogTurnWindow(
        thread_id="t1",
        turns=(
            DialogTurn(
                thread_id="t1",
                role="user",
                content="вот обращение",
                payload=attachment_ids_payload((doc_id,)),
                seq=0,
            ),
            DialogTurn(
                thread_id="t1",
                role="assistant",
                content="Сводка документа…",
                seq=1,
            ),
        ),
    )
    decision = AttachmentStickinessPolicy.decide_rehydrate(
        continuation_kind="format",
        refers_to_prior=True,
        has_turn_attachments=False,
        dialog=window,
        prior_context="Сводка документа…",
        trust_prior_for_workers=False,
    )
    assert decision.clear_pending is True
    assert decision.attachment_ids == ()
    assert decision.reason == "clear_pending:format"


def test_rehydrate_format_uses_prior_attachment_ids() -> None:
    doc_id = uuid4()
    webp_id = uuid4()
    window = DialogTurnWindow(
        thread_id="t1",
        turns=(
            DialogTurn(
                thread_id="t1",
                role="user",
                content="вот обращение",
                payload=attachment_ids_payload((doc_id,)),
                seq=0,
            ),
            DialogTurn(
                thread_id="t1",
                role="assistant",
                content="Уважаемая Татьяна Васильевна! Ответ на обращение…",
                seq=1,
            ),
            DialogTurn(
                thread_id="t1",
                role="user",
                content="файл с ценами",
                payload=attachment_ids_payload((webp_id,)),
                seq=2,
            ),
            DialogTurn(
                thread_id="t1",
                role="assistant",
                content="Цены на иван-чай 3000–5000",
                seq=3,
            ),
        ),
    )
    decision = AttachmentStickinessPolicy.decide_rehydrate(
        continuation_kind="format",
        refers_to_prior=True,
        has_turn_attachments=False,
        dialog=window,
        prior_context="Уважаемая Татьяна Васильевна! Ответ на обращение…",
        trust_prior_for_workers=True,
    )
    assert decision.attachment_ids == (doc_id,)
    assert decision.reason == "rehydrate_prior_attachments"
