"""W7b: revision identity is a content hash the server computes (050, 075).

The LLM returns a whole document, never block ids: an invented id would highlight the
wrong paragraph. Identity therefore has to be derived and stable — same text, same id;
moved block, still the same block. These tests pin the derivation and the two gates that
keep a diff honest: a revision signal (``RevisionPolicy``) and a readable previous answer.
"""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.intent_turn_helpers import (
    ASSISTANT_TURN_SCHEMA,
    assistant_revision,
    assistant_turn_payload,
    stream_result_frame,
    turn_revision,
)
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import (
    ContentDocument,
    DocumentRevision,
    block_content_hash,
    document_content_hash,
    document_revision,
    parse_content_document,
)
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.domain.policies.revision import RevisionPolicy


def _doc(*paragraphs: str, title: str | None = None, locale: str = "ru-RU") -> ContentDocument:
    return parse_content_document(
        {
            "locale": locale,
            "title": title,
            "blocks": [{"type": "paragraph", "text": text} for text in paragraphs],
            "meta": {"confidence": 0.9, "kind": "response"},
        }
    )


def _result(document: ContentDocument | None) -> FormatterTaskResult:
    return FormatterTaskResult(
        task_id="t1",
        agent_role="formatter",
        status="success",
        confidence=0.9,
        requires_review=False,
        output=document,
    )


def _window(*documents: ContentDocument | None) -> DialogTurnWindow:
    turns = []
    for index, document in enumerate(documents):
        payload = None
        if document is not None:
            payload = {"schema": ASSISTANT_TURN_SCHEMA, "document": document.model_dump(mode="json"), "hitl_cards": []}
        turns.append(DialogTurn(thread_id="thread-1", role="assistant", content=f"turn {index}", payload=payload, seq=index))
    return DialogTurnWindow(thread_id="thread-1", turns=tuple(turns), limit=12)


def test_block_hash_is_content_identity_not_position() -> None:
    first = _doc("Срок — 10 дней.").blocks[0]
    moved = _doc("Другое.", "Срок — 10 дней.").blocks[1]

    assert block_content_hash(first) == block_content_hash(moved)
    assert block_content_hash(first) != block_content_hash(_doc("Срок — 30 дней.").blocks[0])


def test_document_hash_ignores_meta_that_changes_every_generation() -> None:
    base = _doc("Ответ.")
    rerendered = parse_content_document(
        {
            "locale": "ru-RU",
            "blocks": [{"type": "paragraph", "text": "Ответ."}],
            "meta": {"confidence": 0.42, "kind": "response", "requires_review": True},
        }
    )

    assert document_content_hash(base) == document_content_hash(rerendered)
    assert document_content_hash(base) != document_content_hash(_doc("Ответ иной."))


def test_diff_reports_new_and_removed_blocks_with_the_previous_identity() -> None:
    previous = _doc("Было первое.", "Было второе.")
    current = _doc("Было первое.", "Стало третьим.")

    revision = document_revision(previous, current)

    assert revision.revision_of == document_content_hash(previous)
    assert revision.changed_blocks == (block_content_hash(current.blocks[1]),)
    assert revision.changed_block_indices == (1,)
    assert revision.removed_blocks == (block_content_hash(previous.blocks[1]),)
    assert revision.unchanged_blocks == 1


def test_diff_points_at_positions_in_the_current_document() -> None:
    """UI paints from indices: a hash alone cannot be mapped without re-implementing it."""
    current = _doc("Новое первое.", "Старое.", "Новое третье.")
    revision = document_revision(_doc("Старое."), current)

    assert revision.changed_blocks == (
        block_content_hash(current.blocks[0]),
        block_content_hash(current.blocks[2]),
    )
    assert revision.changed_block_indices == (0, 2)


def test_moving_a_block_is_not_a_change() -> None:
    """Identity is content: reordering the same paragraphs edits nothing."""
    revision = document_revision(_doc("A.", "B."), _doc("B.", "A."))

    assert revision.changed_blocks == ()
    assert revision.changed_block_indices == ()
    assert revision.removed_blocks == ()
    assert revision.unchanged_blocks == 2


def test_duplicate_blocks_are_counted_not_collapsed() -> None:
    """Deleting one of two identical paragraphs is a real removal."""
    duplicate = block_content_hash(_doc("Повтор.").blocks[0])

    removed = document_revision(_doc("Повтор.", "Повтор."), _doc("Повтор."))
    assert removed.removed_blocks == (duplicate,)
    assert removed.changed_blocks == ()
    assert removed.changed_block_indices == ()
    assert removed.unchanged_blocks == 1

    added = document_revision(_doc("Повтор."), _doc("Повтор.", "Повтор."))
    assert added.changed_blocks == (duplicate,)
    assert added.changed_block_indices == (1,)
    assert added.unchanged_blocks == 1


@pytest.mark.parametrize("transformation", ("restructure", "expand", "shorten", "rewrite"))
def test_a_transform_of_the_prior_answer_continues_its_lineage(transformation: str) -> None:
    assert RevisionPolicy.continues_prior_document(revision_feedback=None, transformation=transformation)


def test_feedback_means_the_previous_answer_was_rejected() -> None:
    assert RevisionPolicy.continues_prior_document(revision_feedback="сделай короче", transformation="none")
    assert not RevisionPolicy.continues_prior_document(revision_feedback="   ", transformation="none")
    assert not RevisionPolicy.continues_prior_document(revision_feedback=None, transformation="none")
    assert not RevisionPolicy.continues_prior_document(revision_feedback=None, transformation="unknown")


def test_revision_needs_signal_previous_answer_and_actual_change() -> None:
    previous = _doc("Было.")
    current = _doc("Стало.")
    window = _window(previous)

    assert assistant_revision(_result(current), window, revision_requested=False) is None
    assert assistant_revision(_result(current), _window(), revision_requested=True) is None
    assert assistant_revision(_result(previous), window, revision_requested=True) is None

    revision = assistant_revision(_result(current), window, revision_requested=True)
    assert revision is not None
    assert revision.revision_of == document_content_hash(previous)
    assert revision.changed_blocks == (block_content_hash(current.blocks[0]),)


def test_revision_is_none_without_a_document_to_revise() -> None:
    assert assistant_revision(_result(None), _window(_doc("Было.")), revision_requested=True) is None


def test_an_unreadable_previous_turn_is_skipped_not_raised() -> None:
    """A broken persisted document is a missing diff base, never a failed turn."""
    older = _doc("Было.")
    broken = DialogTurn(
        thread_id="thread-1",
        role="assistant",
        content="broken",
        payload={"schema": ASSISTANT_TURN_SCHEMA, "document": {"blocks": "not-a-list"}, "hitl_cards": []},
        seq=1,
    )
    unknown_schema = DialogTurn(
        thread_id="thread-1",
        role="assistant",
        content="legacy",
        payload={"schema": "assistant_turn_v0", "document": older.model_dump(mode="json")},
        seq=2,
    )
    user_turn = DialogTurn(thread_id="thread-1", role="user", content="вопрос", payload=None, seq=3)
    older_turn = DialogTurn(
        thread_id="thread-1",
        role="assistant",
        content="older answer",
        payload={"schema": ASSISTANT_TURN_SCHEMA, "document": older.model_dump(mode="json")},
        seq=0,
    )
    window = DialogTurnWindow(
        thread_id="thread-1",
        turns=(older_turn, broken, unknown_schema, user_turn),
        limit=12,
    )

    revision = assistant_revision(_result(_doc("Стало.")), window, revision_requested=True)

    assert revision is not None
    assert revision.revision_of == document_content_hash(older)


def test_turn_payload_carries_the_revision_only_when_it_was_computed() -> None:
    document = _doc("Стало.")
    revision = DocumentRevision(revision_of="abc", changed_blocks=("b1",), removed_blocks=(), unchanged_blocks=0)

    without = assistant_turn_payload(_result(document))
    with_revision = assistant_turn_payload(_result(document), revision=revision)

    assert without is not None
    assert "revision" not in without
    assert with_revision is not None
    encoded = json.dumps(with_revision, ensure_ascii=False)
    assert '"revision"' in encoded
    assert with_revision["revision"] == revision.model_dump(mode="json")


def _state(
    window: DialogTurnWindow | None,
    *,
    feedback: str | None = None,
    transformation: str = "none",
) -> AgentGraphState:
    from types import SimpleNamespace
    from typing import cast

    return cast(
        "AgentGraphState",
        {
            "dialog_window": window,
            "revision_feedback": feedback,
            "routing_intent": SimpleNamespace(transformation=transformation),
        },
    )


def test_turn_revision_owns_both_the_decision_and_the_diff() -> None:
    """Callers pass state, not axes: persist and live frames must agree on "revision"."""
    window = _window(_doc("Было."))
    current = _result(_doc("Стало."))

    assert turn_revision(current, _state(window)) is None
    revision = turn_revision(current, _state(window, transformation="shorten"))
    assert revision is not None
    assert revision.changed_block_indices == (0,)
    assert turn_revision(current, _state(window, feedback="сделай короче")) is not None


def test_stream_result_frame_carries_the_revision_only_when_present() -> None:
    """Live turn and hydrated turn read the same shape; absence is absence, not null."""
    revision = DocumentRevision(
        revision_of="abc",
        changed_blocks=("b1",),
        changed_block_indices=(1,),
        removed_blocks=(),
        unchanged_blocks=0,
    )

    without = stream_result_frame(_result(_doc("Стало.")), task_id="t1", thread_id="th1")
    with_revision = stream_result_frame(
        _result(_doc("Стало.")),
        task_id="t1",
        thread_id="th1",
        revision=revision,
    )

    assert without["event"] == "result"
    assert "revision" not in without
    assert with_revision["revision"] == revision.model_dump(mode="json")
    assert with_revision["revision"] == {
        "revision_of": "abc",
        "changed_blocks": ["b1"],
        "changed_block_indices": [1],
        "removed_blocks": [],
        "unchanged_blocks": 0,
    }
