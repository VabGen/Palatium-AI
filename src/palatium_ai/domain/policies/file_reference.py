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
from typing import Final, Literal
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
#: Digit-bearing runs ("скан"+"2") are short but uniquely identify siblings.
_MIN_NAME_RUN_CHARS_WITH_DIGIT = 4
# A refusal never becomes a wall of names.
_MAX_LISTED_NAMES = 5
#: Resolution reasons that mean "the ask named this file" (not a default pick).
_NAMED_REFERENCE_REASONS = frozenset({"name_in_turn_text", "explicit_filename"})
#: Punctuation stripped from a word before it is read as a document name.
_TOKEN_TRIM = ".,;:!?()[]{}«»\"'"  # noqa: S105 — punctuation set, not a credential (017)
#: Closed morphological set of the *document-role* noun (ru/en). When the user
#: omits the space after it («файлаобращение», «fileappeal»), the stem still
#: counts as a named reference. Not an open phrase list — only the role word that
#: structurally introduces a file title (055). Longest-first so ``файлами`` wins
#: over ``файл``.
_DOC_ROLE_PREFIXES: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            "файл",
            "файла",
            "файлу",
            "файлом",
            "файле",
            "файлы",
            "файлов",
            "файлам",
            "файлами",
            "файлах",
            "документ",
            "документа",
            "документу",
            "документом",
            "документе",
            "документы",
            "документов",
            "документам",
            "документами",
            "документах",
            "file",
            "files",
            "document",
            "documents",
            "doc",
            "docs",
        },
        key=len,
        reverse=True,
    )
)
_DOC_ROLE_TOKENS: Final[frozenset[str]] = frozenset(_DOC_ROLE_PREFIXES)
#: Closed set of *name-pointer* words («с названием 3», «by name 3»). Structural
#: introducers of a filename token — not an open phrase list (055).
_NAME_POINTER_TOKENS: Final[frozenset[str]] = frozenset(
    {
        "название",
        "названия",
        "названию",
        "названием",
        "названии",
        "названиями",
        "имя",
        "имени",
        "именем",
        "name",
        "named",
        "filename",
        "dbname",
        "бд",
        "базе",
        "базы",
        "базу",
        "storage",
        "minio",
    }
)
#: Max alphabetic junk after a doc-role stem in a typo token («файлет» → файл+ет).
_DOC_ROLE_TYPO_SUFFIX_MAX = 2


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
    #: Every file the ask covers. Singular resolution carries one id; an explicit
    #: "all files of this dialog" ask carries the whole owner-scoped set, newest first,
    #: so the worker reads N files instead of guessing one (055).
    attachment_ids: tuple[UUID, ...] = ()
    #: User-safe display name of the resolved file (never an internal id).
    filename: str = ""
    #: User-safe display names of the thread's files, for an honest refusal message.
    #: For ``several_names_in_turn_text`` this is the *matched subset*, not every
    #: thread file (W10.1 P0.3 — card must not offer unrelated uploads).
    candidates: tuple[str, ...] = ()
    #: Filename the user asked for when resolution failed (``no_match``); empty otherwise.
    requested_name: str = ""
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
            display_requested = " ".join((filename or "").split())
            return FileReferenceResolution(
                status="no_match" if not exact else "ambiguous",
                candidates=names if not exact else tuple(item.filename for item in exact),
                requested_name=display_requested,
                reason="explicit_filename_unmatched" if not exact else "explicit_filename_ambiguous",
            )

        matched = FileReferencePolicy.match_names(scoped, hint_text=hint_text)
        if len(matched) == 1:
            return _resolved(matched[0], reason="name_in_turn_text")
        if len(matched) > 1:
            matched_names = tuple(item.filename for item in matched)
            return FileReferenceResolution(
                status="ambiguous",
                candidates=matched_names,
                reason="several_names_in_turn_text",
            )

        if _names_foreign_document(scoped, hint_text=hint_text):
            # The ask named a document the dialog does not hold: reading the dialog's
            # only file would answer about the wrong document (020 fail-closed).
            foreign = _first_foreign_document_token(scoped, hint_text=hint_text)
            return FileReferenceResolution(
                status="no_match",
                candidates=names,
                requested_name=foreign,
                reason="names_foreign_document",
            )

        if len(scoped) == 1:
            return _resolved(scoped[0], reason="single_thread_file")
        return FileReferenceResolution(status="ambiguous", candidates=names, reason="several_thread_files")

    @staticmethod
    def resolve_all(candidates: Sequence[FileRefCandidate]) -> FileReferenceResolution:
        """Resolve an ask that explicitly covers *every* file of the dialog.

        Called only when Intent already said the ask spans the whole set
        (``attachment_scope="all"``): the model decides plurality, code decides
        identity. No name matching happens here — «сравни оба файла» names no file,
        and comparing «эти два подхода» names none either, so a verb/numeral heuristic
        would be the wrong layer (055).
        """
        scoped = list(candidates)
        if not scoped:
            return FileReferenceResolution(status="no_candidates", reason="thread_has_no_files")
        names = tuple(item.filename for item in scoped)
        return FileReferenceResolution(
            status="resolved",
            attachment_id=scoped[0].attachment_id,
            attachment_ids=tuple(item.attachment_id for item in scoped),
            filename=_format_names(names),
            candidates=names,
            reason="all_requested",
        )

    @staticmethod
    def is_named_reference(resolution: FileReferenceResolution) -> bool:
        """True when the user *named* this exact thread file (not a default pick).

        ``single_thread_file`` is the policy's convenience fallback for a dialog with
        one document; it is not evidence that an arbitrary ask is about that file, so
        only explicit names may promote the turn to a storage re-read (055).
        """
        return resolution.status == "resolved" and resolution.reason in _NAMED_REFERENCE_REASONS

    @staticmethod
    def promotes_thread_file_reread(resolution: FileReferenceResolution) -> bool:
        """True when code evidence says this ask targets a thread file (W10.1 P0.3).

        Broader than ``is_named_reference``: a unique name still promotes, but so does
        a name that matches several thread files (card over that subset) and a named
        miss (``requested_name`` set → refusal, not knowledge search). Bare
        ``several_thread_files`` / ``single_thread_file`` stay Intent-driven so an
        unrelated ask cannot drag dialog uploads into the answer (055).
        """
        if FileReferencePolicy.is_named_reference(resolution):
            return True
        if resolution.status == "ambiguous" and resolution.reason == "several_names_in_turn_text":
            return True
        return resolution.status == "no_match" and bool((resolution.requested_name or "").strip())

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
            asked = " ".join((resolution.requested_name or "").split())
            if asked and names:
                return f"Файл с именем «{asked}» не найден; доступны: {names}. Назовите файл, который нужно перечитать."
            if asked:
                return f"Файл с именем «{asked}» не найден среди файлов этого диалога. Назовите его точнее или приложите файл."
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

        Structural gates, no word lists:
        * occurrences must be delimiter-bounded — a name glued into a longer word
          (``...обращением``) is not a document reference;
        * a full stem as a bounded token selects the file when it uniquely identifies
          one thread candidate (``обращение`` → ``Обращение.docx`` among others);
        * a multi-word / digit-bearing run of the name (``скан_2``, ``кодекс
          корпоративной этики``) counts when it uniquely points at one title.
        Uniqueness is enforced by the caller (``len(matched) == 1``); this method
        only collects candidates that the ask *could* name.
        """
        haystack = _normalize_text(hint_text[:_HINT_SCAN_CHARS])
        if not haystack:
            return []
        haystack_words = _name_words(haystack)
        # Strong evidence (full name / stem / multi-word run) outranks a shared
        # leading title token («Скан» among siblings). Otherwise a precise ask for
        # «Скан 1_Приложение.pdf» would also match «Скан 2_…» via the prefix and
        # collapse into a false ambiguous card (W10.1 P0.3).
        strong: list[FileRefCandidate] = []
        weak: list[FileRefCandidate] = []
        for item in candidates:
            name = _normalize_name(item.filename)
            if not name:
                continue
            stem = _normalize_name(_strip_extension(item.filename))
            if (
                _occurs_as_bounded_token(haystack, name)
                or _stem_token_matches(haystack, stem, haystack_words=haystack_words)
                or _name_run_matches(haystack_words, stem)
            ):
                strong.append(item)
                continue
            if not _leading_title_token_matches(haystack, stem):
                continue
            # Doc-role / name-pointer before the lead («файл договор», «с названием
            # Скан») is structural evidence of a file title — promote to strong even
            # for multi-token stems. Bare lead in prose stays weak (055).
            if _leading_title_introduced_in_ask(haystack_words, stem):
                strong.append(item)
            else:
                weak.append(item)
        if strong:
            return strong
        # A lone leading-title hit on a multi-token stem is ordinary prose
        # («подписали договор…» ≠ «Договор_оказания_услуг.docx»). Keep weak
        # matches only when they disambiguate siblings («Скан» → card) or when
        # the stem itself is a single substantive token (055).
        if len(weak) == 1 and _stem_substantive_token_count(_normalize_name(_strip_extension(weak[0].filename))) >= 2:
            return []
        return weak


def _resolved(candidate: FileRefCandidate, *, reason: str) -> FileReferenceResolution:
    return FileReferenceResolution(
        status="resolved",
        attachment_id=candidate.attachment_id,
        attachment_ids=(candidate.attachment_id,),
        filename=candidate.filename,
        candidates=(candidate.filename,),
        reason=reason,
    )


def _strip_extension(filename: str) -> str:
    head, separator, _tail = filename.rpartition(".")
    return head if separator and head else filename


def _stem_token_matches(
    haystack: str,
    stem: str,
    *,
    haystack_words: Sequence[str] | None = None,
) -> bool:
    """True when the full extension-stripped stem occurs as a bounded token in the ask.

    Single plain stems (``обращение`` for ``Обращение.docx``) are allowed: among
    several thread files uniqueness still gates resolution. Inflected prose
    (``обращением``) stays unbounded and does not match (055). A missing space
    after the document-role noun (``файлаобращение``) is still a named reference:
    the role prefix is structural, not a title inflection.

    Digit-only / otherwise-too-short stems (``3.pdf``) match only when the ask
    *introduces* them as a file name — doc-role, name-pointer, or glued role —
    so bare «за 3 минуты» does not steal ``3.pdf`` (055).
    """
    words = list(haystack_words) if haystack_words is not None else _name_words(haystack)
    if len(stem) >= _MIN_NAME_MATCH_CHARS:
        if _occurs_as_bounded_token(haystack, stem):
            return True
        return _occurs_glued_after_doc_role(haystack, stem)
    if not stem or not stem.isalnum():
        return False
    if _short_stem_introduced_in_ask(words, stem):
        return True
    return _occurs_glued_after_doc_role(haystack, stem, allow_short=True)


def _short_stem_introduced_in_ask(haystack_words: Sequence[str], stem: str) -> bool:
    """True when ``stem`` is a bounded token right after a file-name introducer.

    Covers «файл 3», «файле 3», «файлет 3» (role typo), «с названием 3», «в БД 3».
    """
    stem_l = stem.casefold()
    for index, word in enumerate(haystack_words):
        if word != stem_l:
            continue
        if index == 0:
            continue
        prev = haystack_words[index - 1]
        if prev in _DOC_ROLE_TOKENS or prev in _NAME_POINTER_TOKENS:
            return True
        if _token_extends_doc_role(prev):
            return True
    return False


def _token_extends_doc_role(token: str) -> bool:
    """True for a doc-role token with a short alphabetic typo suffix («файлет»)."""
    if token in _DOC_ROLE_TOKENS:
        return True
    for prefix in _DOC_ROLE_PREFIXES:
        if not token.startswith(prefix):
            continue
        rem = token[len(prefix) :]
        if 0 < len(rem) <= _DOC_ROLE_TYPO_SUFFIX_MAX and rem.isalpha():
            return True
    return False


def _occurs_glued_after_doc_role(
    haystack: str,
    stem: str,
    *,
    allow_short: bool = False,
) -> bool:
    """True when a haystack token is exactly ``<doc-role><stem>`` (omitted space).

    ``файлаобращение`` → role ``файла`` + stem ``обращение``. Ordinary compounds
    that merely *contain* the stem (``обращением``) stay unmatched: they have no
    document-role prefix from the closed set. ``allow_short`` covers ``файл3``.
    """
    if len(stem) < _MIN_NAME_MATCH_CHARS and not allow_short:
        return False
    if not stem:
        return False
    for token in _name_words(haystack):
        if len(token) <= len(stem):
            continue
        for prefix in _DOC_ROLE_PREFIXES:
            if len(token) != len(prefix) + len(stem):
                continue
            if token.startswith(prefix) and token.endswith(stem):
                return True
    return False


def _leading_title_token_matches(haystack: str, stem: str) -> bool:
    """True when the ask names the leading title word of the file (``Скан`` → ``Скан 1_…``).

    Interior title words (``рынку`` inside ``Отчет по рынку``) are *not* evidence —
    that would turn ordinary prose into a false document reference (055). Only the
    first alphabetic token of the stem counts; uniqueness still gates resolution, so
    a shared prefix (``Скан`` among siblings) yields ``ambiguous`` over that subset.
    """
    lead = _leading_title_token(stem)
    if not lead:
        return False
    return _occurs_as_bounded_token(haystack, lead)


def _leading_title_token(stem: str) -> str:
    """First alphabetic title token of a stem, or empty when none qualifies."""
    words = _name_words(stem)
    if not words:
        return ""
    lead = words[0]
    if lead.isdigit() or len(lead) < _MIN_NAME_MATCH_CHARS:
        return ""
    return lead


def _leading_title_introduced_in_ask(haystack_words: Sequence[str], stem: str) -> bool:
    """True when the leading title token is preceded by a file-name introducer.

    Same structural introducers as short stems (``файл`` / ``название`` / role typo):
    «сделай сводку файла договор» names ``Договор_оказания_услуг.docx``; bare
    «подписали договор» does not (055).
    """
    lead = _leading_title_token(stem)
    if not lead:
        return False
    lead_l = lead.casefold()
    for index, word in enumerate(haystack_words):
        if word != lead_l:
            continue
        if index == 0:
            continue
        prev = haystack_words[index - 1]
        if prev in _DOC_ROLE_TOKENS or prev in _NAME_POINTER_TOKENS:
            return True
        if _token_extends_doc_role(prev):
            return True
    return False


def _stem_substantive_token_count(stem: str) -> int:
    """How many discriminating title tokens the stem carries (digits count)."""
    return sum(1 for word in _name_words(stem) if _run_word_is_substantive(word))


def _name_run_matches(haystack_words: Sequence[str], stem: str) -> bool:
    """True when a long-enough contiguous run of the file name occurs in the ask.

    Digit tokens are discriminators (``скан_2`` → ``Скан 2 _Приложение.pdf``), not
    fluff: they count as substantive even when shorter than the alphabetic minimum.
    """
    name_words = _name_words(stem)
    if len(name_words) < _MIN_NAME_RUN_WORDS:
        return False
    for size in range(len(name_words), _MIN_NAME_RUN_WORDS - 1, -1):
        for start in range(len(name_words) - size + 1):
            run = name_words[start : start + size]
            if not all(_run_word_is_substantive(word) for word in run):
                continue
            min_chars = _MIN_NAME_RUN_CHARS_WITH_DIGIT if any(word.isdigit() for word in run) else _MIN_NAME_RUN_CHARS
            if sum(len(word) for word in run) < min_chars:
                continue
            if _contains_word_run(haystack_words, run):
                return True
    return False


def _run_word_is_substantive(word: str) -> bool:
    """Alphabetic title words need length; digit tokens distinguish siblings (скан 1/2)."""
    if word.isdigit():
        return True
    return len(word) >= _MIN_NAME_RUN_WORD_CHARS


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
    """True when the text names a document the dialog does not hold."""
    return bool(_first_foreign_document_token(candidates, hint_text=hint_text))


def _first_foreign_document_token(candidates: Sequence[FileRefCandidate], *, hint_text: str) -> str:
    """First ``name.ext`` token in the ask that matches no candidate (empty if none).

    Structural test, not a phrase list: a token carrying a supported document
    extension (registry owned by ``domain.attachments.policies``) that matches no
    candidate name means the user asked for *another* file. Without this, a thread
    with a single file would answer about the wrong document.
    """
    haystack = _normalize_text(hint_text[:_HINT_SCAN_CHARS])
    if not haystack:
        return ""
    names = {_normalize_name(item.filename) for item in candidates}
    extensions = supported_document_extensions()
    for token in haystack.split():
        cleaned = token.strip(_TOKEN_TRIM)
        dot = cleaned.rfind(".")
        if dot <= 0 or cleaned[dot:] not in extensions:
            continue
        if _token_identifies_candidate(cleaned, names):
            continue
        return cleaned
    return ""


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
