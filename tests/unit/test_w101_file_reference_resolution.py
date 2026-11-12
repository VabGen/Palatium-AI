"""W10.1 P0.3 — deterministic attachment name resolution (no LLM guess)."""

from __future__ import annotations

from uuid import uuid4

from palatium_ai.domain.policies.file_reference import FileRefCandidate, FileReferencePolicy


def _c(name: str) -> FileRefCandidate:
    return FileRefCandidate(attachment_id=uuid4(), filename=name)


def test_w101_attachment_unique_name_resolves_without_prompt() -> None:
    target = _c("Скан 1_Приложение.pdf")
    others = [
        _c("Скан 2_Приложение.pdf"),
        _c("Договор.pdf"),
        _c("Устав.docx"),
    ]
    resolution = FileReferencePolicy.resolve(
        [target, *others],
        hint_text="перечитай Скан 1_Приложение.pdf",
    )
    assert resolution.status == "resolved"
    assert resolution.attachment_id == target.attachment_id
    assert resolution.reason == "name_in_turn_text"


def test_w101_attachment_partial_name_resolves() -> None:
    target = _c("Скан 1_Приложение.pdf")
    resolution = FileReferencePolicy.resolve(
        [target, _c("Скан 2_Приложение.pdf"), _c("Договор.pdf"), _c("Устав.docx")],
        hint_text="перечитай Скан 1",
    )
    assert resolution.status == "resolved"
    assert resolution.attachment_id == target.attachment_id


def test_w101_attachment_ambiguous_prompts_subset() -> None:
    scan1 = _c("Скан 1_Приложение.pdf")
    scan2 = _c("Скан 2_Приложение.pdf")
    other = _c("Договор.pdf")
    other2 = _c("Устав.docx")
    resolution = FileReferencePolicy.resolve(
        [scan1, scan2, other, other2],
        hint_text="перечитай Скан",
    )
    assert resolution.status == "ambiguous"
    assert resolution.reason == "several_names_in_turn_text"
    assert set(resolution.candidates) == {scan1.filename, scan2.filename}
    assert other.filename not in resolution.candidates
    assert other2.filename not in resolution.candidates


def test_w101_attachment_not_found_lists_available() -> None:
    resolution = FileReferencePolicy.resolve(
        [_c("Скан 1_Приложение.pdf"), _c("Договор.pdf")],
        hint_text="перечитай missing-report.pdf",
    )
    assert resolution.status == "no_match"
    message = FileReferencePolicy.refusal_message(resolution)
    assert "не найден" in message.casefold()
    assert "missing-report.pdf" in message
    assert "Скан 1_Приложение.pdf" in message or "Договор.pdf" in message


def test_w101_attachment_saving_excluded_from_choices() -> None:
    """Resolver candidates are built only from usable rows — saving never enters policy."""
    # Policy itself only sees ready/indexed candidates; simulate that filter.
    ready = _c("ready.pdf")
    resolution = FileReferencePolicy.resolve(
        [ready],
        hint_text="перечитай saving.pdf",
    )
    assert resolution.status == "no_match"
    assert resolution.candidates == (ready.filename,)
    message = FileReferencePolicy.refusal_message(resolution)
    assert "saving.pdf" in message
    assert "ready.pdf" in message


def test_w101_promotes_thread_file_reread_for_name_asks() -> None:
    """Continuity must promote name-driven asks, not only unique resolved matches."""
    scan1 = _c("Скан 1_Приложение.pdf")
    scan2 = _c("Скан 2_Приложение.pdf")
    other = _c("Договор.pdf")
    unique = FileReferencePolicy.resolve([scan1, scan2, other], hint_text="перечитай Скан 1")
    ambiguous = FileReferencePolicy.resolve([scan1, scan2, other], hint_text="перечитай Скан")
    missing = FileReferencePolicy.resolve([scan1, other], hint_text="перечитай missing-report.pdf")
    bare = FileReferencePolicy.resolve([scan1, scan2], hint_text="перечитай этот файл")
    assert FileReferencePolicy.promotes_thread_file_reread(unique) is True
    assert FileReferencePolicy.promotes_thread_file_reread(ambiguous) is True
    assert FileReferencePolicy.promotes_thread_file_reread(missing) is True
    assert FileReferencePolicy.promotes_thread_file_reread(bare) is False
