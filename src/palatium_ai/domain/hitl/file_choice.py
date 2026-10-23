# src/palatium_ai/domain/hitl/file_choice.py

"""Clickable file-choice card for an ambiguous thread-file re-read (020, 055, 070).

When the reference resolver refuses to guess which thread file the user meant, the
refusal is upgraded to a card whose options are the files the thread actually holds
(``AttachmentRepositoryPort.list_for_thread``). Options are never LLM-invented.

The action id is a server-owned ordinal, not an attachment UUID: ids stay behind the
owner-scoped repository and the resume path maps the pick back by *name*. That keeps
the card free of internal identifiers (the same leak class ``InternalVocabularyPolicy``
guards) while remaining deterministic.
"""

from __future__ import annotations

from collections.abc import Sequence

from palatium_ai.domain.content import ActionSpec

#: Server-owned namespace for picked-file actions (never a raw attachment id).
FILE_CHOICE_ACTION_PREFIX = "filesel_"
#: Explicit "use the whole set" option. It carries no id: the resume path re-fences
#: the turn's own uploads from the session (never the thread's older files).
ALL_FILES_ACTION_ID = f"{FILE_CHOICE_ACTION_PREFIX}all"
#: Cards stay scannable; the plain refusal text keeps listing what does not fit.
MAX_FILE_CHOICE_OPTIONS = 8
_NAME_MAX_CHARS = 200
#: Minimum options for a card — one candidate is resolved without asking.
_MIN_OPTIONS = 2


class FileChoiceCardPolicy:
    """Pure: candidate filenames → card actions, framing and resume recognition."""

    @staticmethod
    def distinct_names(
        names: Sequence[str],
        *,
        limit: int = MAX_FILE_CHOICE_OPTIONS,
    ) -> tuple[str, ...]:
        """Deduplicate (case-insensitive) and cap display names, preserving order."""
        seen: list[str] = []
        keys: set[str] = set()
        capped = max(1, limit)
        for raw in names:
            name = " ".join((raw or "").split())[:_NAME_MAX_CHARS]
            if not name:
                continue
            key = name.casefold()
            if key in keys:
                continue
            keys.add(key)
            seen.append(name)
            if len(seen) >= capped:
                break
        return tuple(seen)

    @classmethod
    def mintable(cls, names: Sequence[str]) -> bool:
        """A card needs at least two distinct files — one candidate is not ambiguous."""
        return len(cls.distinct_names(names)) >= _MIN_OPTIONS

    @classmethod
    def build_actions(
        cls,
        names: Sequence[str],
        *,
        include_all: bool = False,
    ) -> tuple[ActionSpec, ...]:
        """One action per distinct file; label is the user's own filename.

        ``include_all`` appends an explicit whole-set option (current-upload turns
        where "по всем файлам" is a legitimate answer to the ambiguity card).
        """
        distinct = cls.distinct_names(names)
        actions = [
            ActionSpec(
                action_id=f"{FILE_CHOICE_ACTION_PREFIX}{index}",
                label=name,
                kind="custom",
                style="primary" if index == 1 else "secondary",
            )
            for index, name in enumerate(distinct, start=1)
        ]
        if include_all and distinct:
            actions.append(
                ActionSpec(
                    action_id=ALL_FILES_ACTION_ID,
                    label="Все файлы",
                    kind="custom",
                    style="secondary",
                )
            )
        return tuple(actions)

    @staticmethod
    def is_file_choice(action_id: str) -> bool:
        """True for an id this policy minted (``filesel_<ordinal>`` / ``filesel_all``)."""
        cleaned = (action_id or "").strip()
        if cleaned == ALL_FILES_ACTION_ID:
            return True
        if not cleaned.startswith(FILE_CHOICE_ACTION_PREFIX):
            return False
        ordinal = cleaned[len(FILE_CHOICE_ACTION_PREFIX) :]
        return ordinal.isdigit() and int(ordinal) >= 1

    @staticmethod
    def is_all_files(action_id: str) -> bool:
        """True for the explicit whole-set option (never a filename)."""
        return (action_id or "").strip() == ALL_FILES_ACTION_ID

    @staticmethod
    def framing(count: int) -> str:
        """User-facing lead-in; names live on the actions, never internal keys."""
        return f"В этом диалоге несколько файлов ({count}). Выберите, какой именно нужно перечитать."

    @staticmethod
    def card_title() -> str:
        return "Выберите файл"


__all__ = [
    "ALL_FILES_ACTION_ID",
    "FILE_CHOICE_ACTION_PREFIX",
    "MAX_FILE_CHOICE_OPTIONS",
    "FileChoiceCardPolicy",
]
