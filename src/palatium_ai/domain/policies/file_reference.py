# src/palatium_ai/domain/policies/file_reference.py

"""Deterministic resolution of a thread-bound file reference (055, 070).

When the user asks to re-read a file that was uploaded earlier in the dialog
(«взять из БД и ещё раз прочитать»), the *identity* of that file must be resolved
in code — never by the LLM. The model can name a file, but it cannot be trusted to
choose one: picking the wrong document is exactly the cross-file bleed the P0 fence
contracts forbid (``AttachmentStickinessPolicy``).

The policy is pure: it receives already owner/thread-scoped candidates and returns a
closed-vocabulary outcome. ``ambiguous`` / ``no_match`` are refusals, not best-effort
guesses (020 fail-closed).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.attachments.policies import supported_document_extensions

#: Outcome of one reference resolution attempt.
FileReferenceStatus = Literal["resolved", "ambiguous", "no_candidates", "no_match"]

# A name shorter than this (after stripping the extension) matches too much text to
# be evidence that the user meant *that* file ("a.pdf", "1.docx").
_MIN_NAME_MATCH_CHARS = 3
_HINT_SCAN_CHARS = 20_000
# A refusal never becomes a wall of names.
_MAX_LISTED_NAMES = 5
#: Punctuation stripped from a word before it is read as a document name.
_TOKEN_TRIM = ".,;:!?()[]{}«»\"'"  # noqa: S105 — punctuation set, not a credential (017)


class FileRefCandidate(BaseModel):
    """One owner/thread-scoped attachment a reference may point at."""

    model_config = {"frozen": True}

    attachment_id: UUID
    filename: str = Field(min_length=1, max_length=255)


class FileReferenceResolution(BaseModel):
    """Typed outcome; only ``resolved`` carries an id the caller may act on."""

    model_config = {"frozen": True}

    status: FileReferenceStatus
    attachment_id: UUID | None = None
    #: User-safe display name of the resolved file (never an internal id).
    filename: str = ""
    #: User-safe display names of the thread's files, for an honest refusal message.
    candidates: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=128)


class FileReferencePolicy:
    """Pure resolver: candidates + turn text → resolved id or typed refusal."""

    @staticmethod
    def resolve(
        candidates: Sequence[FileRefCandidate],
        *,
        hint_text: str = "",
        filename: str = "",
    ) -> FileReferenceResolution:
        """Resolve the referent of a thread-file ask.

        Precedence (structural, no phrase lists):
            1. explicit ``filename`` → exact normalized name match;
            2. a file name occurring in ``hint_text`` (user ask + trusted prior);
            3. the only thread candidate;
            otherwise ``ambiguous`` (several referents) or ``no_match``.
        """
        scoped = list(candidates)
        names = tuple(item.filename for item in scoped)
        if not scoped:
            return FileReferenceResolution(status="no_candidates", reason="thread_has_no_files")

        requested = _normalize_name(filename)
        if requested:
            exact = [item for item in scoped if _normalize_name(item.filename) == requested]
            if len(exact) == 1:
                return _resolved(exact[0], reason="explicit_filename")
            return FileReferenceResolution(
                status="no_match" if not exact else "ambiguous",
                candidates=names,
                reason="explicit_filename_unmatched" if not exact else "explicit_filename_ambiguous",
            )

        matched = FileReferencePolicy.match_names(scoped, hint_text=hint_text)
        if len(matched) == 1:
            return _resolved(matched[0], reason="name_in_turn_text")
        if len(matched) > 1:
            return FileReferenceResolution(status="ambiguous", candidates=names, reason="several_names_in_turn_text")

        if _names_foreign_document(scoped, hint_text=hint_text):
            # The ask named a document the dialog does not hold: reading the dialog's
            # only file would answer about the wrong document (020 fail-closed).
            return FileReferenceResolution(status="no_match", candidates=names, reason="names_foreign_document")

        if len(scoped) == 1:
            return _resolved(scoped[0], reason="single_thread_file")
        return FileReferenceResolution(status="ambiguous", candidates=names, reason="several_thread_files")

    @staticmethod
    def refusal_message(resolution: FileReferenceResolution) -> str:
        """User-facing explanation for a non-resolved reference (020, 055).

        Lives here (next to the resolution semantics) for the same reason
        ``GroundingPolicy.required_empty_clarification`` does: one owner for the
        phrasing, unit-testable, and never assembled by the LLM. The text names the
        situation — never an internal context key, field or row id.
        """
        if resolution.status == "no_candidates":
            if resolution.reason == "thread_files_not_readable":
                return (
                    "Загруженный файл сейчас недоступен для чтения: он удалён или ещё обрабатывается. "
                    "Загрузите его заново, если нужно разобрать содержимое."
                )
            return "В этом диалоге нет загруженных файлов, которые можно прочитать. Приложите файл — и я разберу его содержимое."
        if resolution.status == "ambiguous":
            names = _format_names(resolution.candidates)
            if names:
                return f"В этом диалоге несколько файлов: {names}. Уточните, какой именно нужно перечитать."
            return "В этом диалоге несколько подходящих файлов. Уточните, какой именно нужно перечитать."
        if resolution.status == "no_match":
            names = _format_names(resolution.candidates)
            if names:
                return (
                    f"Не удалось сопоставить запрос с файлами этого диалога ({names}). Назовите файл, который нужно перечитать."
                )
            return "Не удалось найти запрошенный файл среди файлов этого диалога. Назовите его точнее."
        return ""  # pragma: no cover - resolved carries no refusal

    @staticmethod
    def match_names(
        candidates: Sequence[FileRefCandidate],
        *,
        hint_text: str,
    ) -> list[FileRefCandidate]:
        """Candidates whose name (or long-enough stem) occurs in ``hint_text``."""
        haystack = _normalize_text(hint_text[:_HINT_SCAN_CHARS])
        if not haystack:
            return []
        matched: list[FileRefCandidate] = []
        for item in candidates:
            name = _normalize_name(item.filename)
            if not name:
                continue
            if name in haystack:
                matched.append(item)
                continue
            stem = _normalize_name(_strip_extension(item.filename))
            if len(stem) >= _MIN_NAME_MATCH_CHARS and stem in haystack:
                matched.append(item)
        return matched


def _resolved(candidate: FileRefCandidate, *, reason: str) -> FileReferenceResolution:
    return FileReferenceResolution(
        status="resolved",
        attachment_id=candidate.attachment_id,
        filename=candidate.filename,
        candidates=(candidate.filename,),
        reason=reason,
    )


def _strip_extension(filename: str) -> str:
    head, separator, _tail = filename.rpartition(".")
    return head if separator and head else filename


def _names_foreign_document(candidates: Sequence[FileRefCandidate], *, hint_text: str) -> bool:
    """True when the text names a document the dialog does not hold.

    Structural test, not a phrase list: a token carrying a supported document
    extension (registry owned by ``domain.attachments.policies``) that matches no
    candidate name means the user asked for *another* file. Without this, a thread
    with a single file would answer about the wrong document.
    """
    haystack = _normalize_text(hint_text[:_HINT_SCAN_CHARS])
    if not haystack:
        return False
    names = {_normalize_name(item.filename) for item in candidates}
    extensions = supported_document_extensions()
    for token in haystack.split():
        cleaned = token.strip(_TOKEN_TRIM)
        dot = cleaned.rfind(".")
        if dot <= 0 or cleaned[dot:] not in extensions:
            continue
        if _token_identifies_candidate(cleaned, names):
            continue
        return True
    return False


def _token_identifies_candidate(token: str, names: set[str]) -> bool:
    """True when a ``name.ext`` token refers to one of the candidate files.

    A stored name may contain spaces, so the ask may quote only its tail
    ("9.03-2025.pdf" for "СФУТ 9.03-2025.pdf"): containment in either direction,
    on the whole token or on its extension-less stem, counts as identification.
    """
    if not names:
        return False
    stem = token.rpartition(".")[0]
    for name in names:
        if token in name:
            return True
        name_stem = name.rpartition(".")[0]
        if len(stem) < _MIN_NAME_MATCH_CHARS or len(name_stem) < _MIN_NAME_MATCH_CHARS:
            continue
        if stem in name_stem or name_stem in stem:
            return True
    return False


def _format_names(names: Sequence[str]) -> str:
    seen: list[str] = []
    for name in names:
        if name and name not in seen:
            seen.append(name)
        if len(seen) >= _MAX_LISTED_NAMES:
            break
    return ", ".join(f"«{name}»" for name in seen)


def _normalize_name(filename: str) -> str:
    return _normalize_text(filename)


def _normalize_text(text: str) -> str:
    """Trim + collapse whitespace + casefold; keeps filename punctuation intact."""
    return " ".join(text.split()).casefold()


__all__ = [
    "FileRefCandidate",
    "FileReferencePolicy",
    "FileReferenceResolution",
    "FileReferenceStatus",
]
