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


def test_assistant_prose_word_does_not_select_an_unrelated_file() -> None:
    """Regression: «кто заявитель и истец» in a thread with two files is ambiguous.

    The previous assistant answer mentions «обращение» in ordinary prose; that word
    must not resolve ``Обращение.docx`` and read a file the turn never named (055).
    """
    letter = _candidate("Обращение.docx")
    code = _candidate("Кодекс_корпоративной_этики_V2_0_ред_10(1).docx")
    resolution = FileReferencePolicy.resolve([letter, code], hint_text="кто заявитель и истец")
    assert resolution.status == "ambiguous"
    assert resolution.reason == "several_thread_files"
    assert resolution.attachment_id is None


@pytest.mark.parametrize("text", ("составь ответ на обращение", "в ответ на ваше обращением"))
def test_plain_word_in_user_text_is_not_a_document_reference(text: str) -> None:
    """A generic word is prose, not a name: the thread has two files → card, no read."""
    resolution = FileReferencePolicy.resolve(
        [
            _candidate("Обращение.docx"),
            _candidate("Кодекс_корпоративной_этики_V2_0_ред_10(1).docx"),
        ],
        hint_text=text,
    )
    assert resolution.status == "ambiguous"
    assert resolution.attachment_id is None


def test_name_shaped_stem_still_resolves() -> None:
    """User-authored name-shaped stem (digits or several words) remains sufficient."""
    target = _candidate("Годовой отчет 2025.pdf")
    resolution = FileReferencePolicy.resolve(
        [target, _candidate("Обращение.docx")],
        hint_text="перечитай годовой отчет 2025 ещё раз",
    )
    assert resolution.status == "resolved"
    assert resolution.attachment_id == target.attachment_id
    assert resolution.reason == "name_in_turn_text"


def test_multi_word_title_resolves_the_named_thread_file() -> None:
    """Regression: «Кодекс_корпоративной_этики_V2_0_ред_10(1).docx» must be re-read.

    The underscore-separated file name never appears verbatim in the ask, so a
    turn that named it fell into ``ambiguous`` and refused to read storage. A
    contiguous run of the name's words is a name reference (055).
    """
    letter = _candidate("Обращение.docx")
    code = _candidate("Кодекс_корпоративной_этики_V2_0_ред_10(1).docx")
    resolution = FileReferencePolicy.resolve(
        [letter, code],
        hint_text="покажи полный текст файла Кодекс корпоративной этики",
    )
    assert resolution.status == "resolved"
    assert resolution.attachment_id == code.attachment_id
    assert resolution.reason == "name_in_turn_text"


def test_short_generic_phrase_does_not_select_a_file_by_title_run() -> None:
    """A run needs substantive words: «что по рынку» is prose, not a title."""
    report = _candidate("Отчет по рынку 2025.docx")
    other = _candidate("Обращение.docx")
    resolution = FileReferencePolicy.resolve([report, other], hint_text="что по рынку")
    assert resolution.status == "ambiguous"
    assert resolution.attachment_id is None


def test_only_a_named_reference_promotes_the_turn_to_a_storage_read() -> None:
    """``single_thread_file`` is a convenience pick, not evidence the ask is about it."""
    only = _candidate("СФУТ 9.03-2025.pdf")
    named = FileReferencePolicy.resolve(
        [only, _candidate("ГОСТ 34.602-2020.docx")],
        hint_text="перечитай СФУТ 9.03-2025 ещё раз",
    )
    single = FileReferencePolicy.resolve([only], hint_text="а что там по срокам?")
    assert FileReferencePolicy.is_named_reference(named) is True
    assert FileReferencePolicy.is_named_reference(single) is False
