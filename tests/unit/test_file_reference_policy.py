"""FileReferencePolicy — resolution truth table for a thread file re-read (055)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from palatium_ai.domain.policies.file_reference import (
    FileRefCandidate,
    FileReferencePolicy,
)


def _candidate(name: str, *, attachment_id: UUID | None = None) -> FileRefCandidate:
    return FileRefCandidate(attachment_id=attachment_id or uuid4(), filename=name)


def test_empty_thread_has_no_candidates() -> None:
    resolution = FileReferencePolicy.resolve([], hint_text="перечитай файл")
    assert resolution.status == "no_candidates"
    assert resolution.attachment_id is None
    assert resolution.reason == "thread_has_no_files"


def test_single_thread_file_resolves_without_being_named() -> None:
    only = _candidate("СФУТ 9.03-2025.pdf")
    resolution = FileReferencePolicy.resolve([only], hint_text="а из БД взять этот файл и ещё раз прочитать")
    assert resolution.status == "resolved"
    assert resolution.attachment_id == only.attachment_id
    assert resolution.filename == "СФУТ 9.03-2025.pdf"
    assert resolution.reason == "single_thread_file"


def test_name_in_turn_text_wins_over_single_candidate() -> None:
    named = _candidate("СФУТ 9.03-2025.pdf")
    other = _candidate("ГОСТ 34.602-2020.docx")
    resolution = FileReferencePolicy.resolve([other, named], hint_text="прочитай СФУТ 9.03-2025 ещё раз")
    assert resolution.status == "resolved"
    assert resolution.attachment_id == named.attachment_id
    assert resolution.reason == "name_in_turn_text"


def test_partial_name_with_two_candidates_is_ambiguous() -> None:
    """A tail of a spaced name is not enough evidence when the thread has several files."""
    spaced = _candidate("СФУТ 9.03-2025.pdf")
    other = _candidate("приложение.docx")
    resolution = FileReferencePolicy.resolve([spaced, other], hint_text="открой 9.03-2025 и покажи требования")
    assert resolution.status == "ambiguous"
    assert resolution.attachment_id is None
    assert set(resolution.candidates) == {"СФУТ 9.03-2025.pdf", "приложение.docx"}


def test_two_named_files_are_ambiguous() -> None:
    first = _candidate("СФУТ 9.03-2025.pdf")
    second = _candidate("ГОСТ 34.602-2020.docx")
    resolution = FileReferencePolicy.resolve(
        [first, second],
        hint_text="сравни СФУТ 9.03-2025 и ГОСТ 34.602-2020",
    )
    assert resolution.status == "ambiguous"
    assert resolution.attachment_id is None
    assert set(resolution.candidates) == {"СФУТ 9.03-2025.pdf", "ГОСТ 34.602-2020.docx"}


def test_two_unnamed_files_are_ambiguous() -> None:
    resolution = FileReferencePolicy.resolve(
        [_candidate("a.pdf"), _candidate("b.pdf")],
        hint_text="перечитай этот файл",
    )
    assert resolution.status == "ambiguous"
    assert resolution.reason == "several_thread_files"
    assert resolution.attachment_id is None


def test_explicit_filename_matches_exactly_once() -> None:
    target = _candidate("СФУТ 9.03-2025.pdf")
    resolution = FileReferencePolicy.resolve(
        [target, _candidate("other.pdf")],
        filename=" сфут 9.03-2025.PDF ",
    )
    assert resolution.status == "resolved"
    assert resolution.attachment_id == target.attachment_id
    assert resolution.reason == "explicit_filename"


def test_explicit_unknown_filename_refuses_instead_of_falling_back() -> None:
    resolution = FileReferencePolicy.resolve(
        [_candidate("СФУТ 9.03-2025.pdf")],
        filename="ГОСТ 34.602-2020.docx",
    )
    assert resolution.status == "no_match"
    assert resolution.attachment_id is None
    assert resolution.reason == "explicit_filename_unmatched"


def test_foreign_document_name_does_not_read_the_only_thread_file() -> None:
    """A named document outside the dialog must never resolve to the dialog's file."""
    resolution = FileReferencePolicy.resolve(
        [_candidate("СФУТ 9.03-2025.pdf")],
        hint_text="сравни с ГОСТ 34.602-2020.docx, который я прикладывал",
    )
    assert resolution.status == "no_match"
    assert resolution.attachment_id is None
    assert resolution.reason == "names_foreign_document"


def test_decimal_revision_is_not_a_document_name() -> None:
    """«9.03-2025» is a revision, not an extension: it must not force a refusal."""
    only = _candidate("СФУТ 9.03-2025.pdf")
    resolution = FileReferencePolicy.resolve([only], hint_text="анализ файла СФУТ 9.03-2025")
    assert resolution.status == "resolved"
    assert resolution.attachment_id == only.attachment_id


@pytest.mark.parametrize(
    "status",
    ("ambiguous", "no_candidates", "no_match"),
)
def test_refusal_message_is_user_facing_and_free_of_internal_vocabulary(status: str) -> None:
    from palatium_ai.domain.policies.internal_vocabulary import InternalVocabularyPolicy

    resolutions = {
        "no_candidates": FileReferencePolicy.resolve([], hint_text="прочитай"),
        "ambiguous": FileReferencePolicy.resolve(
            [_candidate("a.pdf"), _candidate("b.pdf")],
            hint_text="прочитай этот файл",
        ),
        "no_match": FileReferencePolicy.resolve(
            [_candidate("a.pdf")],
            hint_text="прочитай missing.pdf",
        ),
    }
    message = FileReferencePolicy.refusal_message(resolutions[status])
    assert message
    assert InternalVocabularyPolicy.find_terms(message) == ()
    assert "attachment_context" not in message


def test_refusal_message_never_lists_more_than_five_names() -> None:
    from palatium_ai.domain.policies.file_reference import FileReferenceResolution

    resolution = FileReferenceResolution(
        status="ambiguous",
        candidates=tuple(f"file-{index}.pdf" for index in range(9)),
        reason="several_thread_files",
    )
    message = FileReferencePolicy.refusal_message(resolution)
    assert message.count("«") == 5


def test_unresolved_resolution_carries_no_attachment_id() -> None:
    resolution = FileReferencePolicy.resolve([], hint_text="")
    assert resolution.attachment_id is None
