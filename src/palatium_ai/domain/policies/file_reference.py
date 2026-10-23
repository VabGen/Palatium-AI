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
# A multi-word name fragment ("кодекс корпоративной этики") is evidence only when it
# is a real title run: several substantive words, not a generic phrase.
_MIN_NAME_RUN_WORDS = 2
_MIN_NAME_RUN_WORD_CHARS = 3
_MIN_NAME_RUN_CHARS = 10
# A refusal never becomes a wall of names.
_MAX_LISTED_NAMES = 5
#: Resolution reasons that mean "the ask named this file" (not a default pick).
_NAMED_REFERENCE_REASONS = frozenset({"name_in_turn_text", "explicit_filename"})
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
            2. a file name occurring in ``hint_text``;
            3. the only thread candidate;
            otherwise ``ambiguous`` (several referents) or ``no_match``.

        ``hint_text`` MUST be user-authored (the current ask, or previous *user*
        turns). Assistant prose is not evidence of a file reference: it names
        words like «обращение» in normal sentences, which would resolve to an
        unrelated thread file (``Обращение.docx``) and be read as if the user
        had asked for it (055/020).
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
    def is_named_reference(resolution: FileReferenceResolution) -> bool:
        """True when the user *named* this exact thread file (not a default pick).

        ``single_thread_file`` is the policy's convenience fallback for a dialog with
        one document; it is not evidence that an arbitrary ask is about that file, so
        only explicit names may promote the turn to a storage re-read (055).
        """
        return resolution.status == "resolved" and resolution.reason in _NAMED_REFERENCE_REASONS

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
        """Candidates whose name (or name-shaped part of it) occurs in ``hint_text``.

        Three structural gates, no word lists:
        * occurrences must be delimiter-bounded — a name glued into a longer word
          (``...обращением``) is not a document reference;
        * a single-word stem counts only when it reads as a name (digit/symbol or
          several words), so an ordinary word like «обращение» cannot select a file;
        * a multi-word run of the name (``кодекс корпоративной этики`` for
          ``Кодекс_корпоративной_этики_V2_0_ред_10(1).docx``) counts when every
          word is substantive and the run is long enough to be a title, not a phrase.
        """
        haystack = _normalize_text(hint_text[:_HINT_SCAN_CHARS])
        if not haystack:
            return []
        haystack_words = _name_words(haystack)
        matched: list[FileRefCandidate] = []
        for item in candidates:
            name = _normalize_name(item.filename)
            if not name:
                continue
            if _occurs_as_bounded_token(haystack, name):
                matched.append(item)
                continue
            stem = _normalize_name(_strip_extension(item.filename))
            if _stem_is_named(haystack, stem) or _name_run_matches(haystack_words, stem):
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


def _stem_is_named(haystack: str, stem: str) -> bool:
    """True when a name-shaped stem of sufficient length occurs as a bounded token."""
    return len(stem) >= _MIN_NAME_MATCH_CHARS and _is_name_shaped(stem) and _occurs_as_bounded_token(haystack, stem)


def _name_run_matches(haystack_words: Sequence[str], stem: str) -> bool:
    """True when a long-enough contiguous run of the file name occurs in the ask."""
    name_words = _name_words(stem)
    if len(name_words) < _MIN_NAME_RUN_WORDS:
        return False
    for size in range(len(name_words), _MIN_NAME_RUN_WORDS - 1, -1):
        for start in range(len(name_words) - size + 1):
            run = name_words[start : start + size]
            if any(len(word) < _MIN_NAME_RUN_WORD_CHARS for word in run):
                continue
            if sum(len(word) for word in run) < _MIN_NAME_RUN_CHARS:
                continue
            if _contains_word_run(haystack_words, run):
                return True
    return False


def _contains_word_run(haystack_words: Sequence[str], run: Sequence[str]) -> bool:
    width = len(run)
    if not width:
        return False
    return any(haystack_words[index : index + width] == run for index in range(len(haystack_words) - width + 1))


def _name_words(text: str) -> list[str]:
    """Split a name or an ask into case-folded words (any non-alphanumeric is a separator)."""
    words: list[str] = []
    current: list[str] = []
    for ch in text.casefold():
        if ch.isalnum():
            current.append(ch)
        elif current:
            words.append("".join(current))
            current = []
    if current:
        words.append("".join(current))
    return words


def _is_name_shaped(stem: str) -> bool:
    """True when a stem reads as a document name, not as ordinary prose.

    Structural shape test, not a word list: a name carries a digit/symbol
    (``СФУТ 9.03-2025``, ``кодекс_корпоративной_этики_v2_0``) or spans several
    words. A single plain word (``обращение``, ``договор``) is regular prose and
    must not turn any sentence into a file reference (055).
    """
    if any(ch.isdigit() or not ch.isalpha() for ch in stem):
        return True
    return len(stem.split()) > 1


def _occurs_as_bounded_token(haystack: str, needle: str) -> bool:
    """True when ``needle`` occurs in ``haystack`` delimited by non-alphanumerics.

    ``обращение`` must not match inside ``обращением``: substring hits inflate a
    plain word into evidence of a document reference (055).
    """
    start = haystack.find(needle)
    while start != -1:
        end = start + len(needle)
        left_bounded = start == 0 or not haystack[start - 1].isalnum()
        right_bounded = end == len(haystack) or not haystack[end].isalnum()
        if left_bounded and right_bounded:
            return True
        start = haystack.find(needle, start + 1)
    return False


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
