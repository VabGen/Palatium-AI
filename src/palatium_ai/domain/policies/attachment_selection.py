"""Deterministic selection of current-turn attachments (Level 1 priority hierarchy).

The resolver answers *which of the files attached to this message* the ask targets,
in code and before any worker runs. No phrase lists: the plurality/modality axes
come from Intent, the file identity from ``FileReferencePolicy.match_names``.

Precedence (top-down, never "scan the whole history"):
    1. an explicit filename in the ask → exactly that file;
    2. a modality named by the ask (image vs document) filters the set;
    3. a plurality axis (``single``) asks the human when several files remain;
    4. otherwise the whole eligible set is the selection.

The policy is pure and unit-testable without a repository or LLM (055).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.policies.file_reference import FileRefCandidate, FileReferencePolicy
from palatium_ai.domain.policies.types import AttachmentKind, AttachmentScope

SelectionStatus = Literal["none", "selected", "ambiguous"]


class AttachmentSelection(BaseModel):
    """Outcome of one selection attempt; only ``selected`` carries prompt blocks."""

    model_config = {"frozen": True}

    status: SelectionStatus
    blocks: tuple[AttachmentContextBlock, ...] = ()
    #: User-safe filenames of every eligible candidate (for the choice card).
    candidates: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=64)
    #: True when the selection is the whole eligible set (not one named file).
    whole_set: bool = False


class AttachmentSelectionPolicy:
    """Pure: current-turn blocks + ask axes → one selected set or an ambiguity."""

    @staticmethod
    def select(
        blocks: Sequence[AttachmentContextBlock],
        *,
        scope: AttachmentScope = "auto",
        kind: AttachmentKind = "any",
        ask: str = "",
    ) -> AttachmentSelection:
        if not blocks:
            return AttachmentSelection(status="none", reason="no_turn_attachments")

        eligible = [block for block in blocks if block.matches_kind(kind)]
        reason_prefix = ""
        if not eligible:
            # The ask named a modality this turn does not hold. Keep the real files
            # fenced (the worker can say what they are) instead of silently handing
            # an empty context to the LLM (020).
            eligible = list(blocks)
            reason_prefix = "kind_no_match_"

        if len(blocks) == 1:
            return AttachmentSelection(
                status="selected",
                blocks=tuple(blocks),
                candidates=_names(blocks),
                reason=f"{reason_prefix}single_turn_file",
                whole_set=True,
            )

        matched = _named(eligible, ask=ask)
        if matched:
            if len(matched) == 1:
                return AttachmentSelection(
                    status="selected",
                    blocks=(matched[0],),
                    candidates=_names(matched),
                    reason=f"{reason_prefix}explicit_name",
                )
            if scope != "single":
                return AttachmentSelection(
                    status="selected",
                    blocks=tuple(matched),
                    candidates=_names(matched),
                    reason=f"{reason_prefix}several_explicit_names",
                    whole_set=len(matched) == len(blocks),
                )
            return AttachmentSelection(
                status="ambiguous",
                candidates=_names(eligible),
                reason="several_explicit_names_single_ask",
            )

        if scope == "single" and len(eligible) > 1:
            # The ask is about one file in the singular and the turn holds several:
            # identity is the human's call, not a guess (020, 055).
            return AttachmentSelection(
                status="ambiguous",
                candidates=_names(eligible),
                reason="several_files_single_ask",
            )

        return AttachmentSelection(
            status="selected",
            blocks=tuple(eligible),
            candidates=_names(eligible),
            reason=f"{reason_prefix}{'all_requested' if scope == 'all' else 'whole_set'}",
            whole_set=len(eligible) == len(blocks),
        )

    @staticmethod
    def needs_decision(
        blocks: Sequence[AttachmentContextBlock],
        *,
        scope: AttachmentScope,
        kind: AttachmentKind,
    ) -> bool:
        """Cheap pre-check: one file, or no modality/plurality, never needs a card."""
        if len(blocks) <= 1:
            return False
        return scope == "single" or kind != "any"


def _named(
    blocks: Sequence[AttachmentContextBlock],
    *,
    ask: str,
) -> list[AttachmentContextBlock]:
    """Blocks whose filename is named in the user's ask (deterministic matcher)."""
    by_id = {block.attachment_id: block for block in blocks}
    candidates = [
        FileRefCandidate(attachment_id=block.attachment_id, filename=block.filename)
        for block in blocks
    ]
    matched = FileReferencePolicy.match_names(candidates, hint_text=ask)
    return [by_id[item.attachment_id] for item in matched if item.attachment_id in by_id]


def _names(blocks: Sequence[AttachmentContextBlock]) -> tuple[str, ...]:
    seen: list[str] = []
    for block in blocks:
        if block.filename not in seen:
            seen.append(block.filename)
    return tuple(seen)


__all__ = ["AttachmentSelection", "AttachmentSelectionPolicy", "SelectionStatus"]
