# src/palatium_ai/domain/policies/attachment_stickiness.py

"""When session sticky attachments may fence the current turn (Super Brain SB1/SB2).

Sticky ``pending_attachment_ids`` must not poison every follow-up: Continuity clears
dialog prior whenever ``untrusted_context`` is non-empty, which stuck the model on
the last upload (webp) and hid earlier document context.

Rules (structural, no phrase lists — 055):
- Explicit upload ids always fence.
- Session pending is NOT auto-restored into the fence at turn start.
- Mid-graph rehydrate only when Continuity ``trust_prior_for_workers`` and
  format / answer+refers_to_prior, and dialog payload carries attachment refs
  tied to the prior being transformed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
    from palatium_ai.domain.policies.types import ContinuationKind


class AttachmentStickinessDecision(BaseModel):
    """Outcome for entry-time sticky resolve."""

    model_config = {"frozen": True}

    restore_ids: tuple[UUID, ...] = ()
    clear_pending: bool = False
    reason: str = Field(min_length=1, max_length=128)


class AttachmentRehydrateDecision(BaseModel):
    """Outcome for mid-graph fence rehydrate after Continuity."""

    model_config = {"frozen": True}

    attachment_ids: tuple[UUID, ...] = ()
    clear_pending: bool = False
    reason: str = Field(min_length=1, max_length=128)


class AttachmentStickinessPolicy:
    """Pure domain policy: sticky restore / clear / format-path rehydrate."""

    @classmethod
    def decide_entry(
        cls,
        *,
        explicit_ids: tuple[UUID, ...] | list[UUID] | None,
        pending_ids: tuple[UUID, ...] | list[UUID],
    ) -> AttachmentStickinessDecision:
        """Entry fence: explicit uploads only; never auto-restore session pending."""
        if explicit_ids:
            ids = tuple(explicit_ids)
            return AttachmentStickinessDecision(
                restore_ids=ids,
                clear_pending=False,
                reason="explicit_upload",
            )
        if pending_ids:
            # Keep pending in session for SB2 rehydrate; do not fence this turn.
            return AttachmentStickinessDecision(
                restore_ids=(),
                clear_pending=False,
                reason="skip_sticky_restore",
            )
        return AttachmentStickinessDecision(
            restore_ids=(),
            clear_pending=False,
            reason="no_attachments",
        )

    @classmethod
    def decide_rehydrate(
        cls,
        *,
        continuation_kind: ContinuationKind | str,
        refers_to_prior: bool,
        has_turn_attachments: bool,
        dialog: DialogTurnWindow | None,
        prior_context: str | None,
        trust_prior_for_workers: bool = False,
    ) -> AttachmentRehydrateDecision:
        """After Continuity: optionally re-fence dialog-bound attachments for format.

        Rehydrate only when Continuity trusted prior for workers — a bare
        ``continuation_kind=format`` after false-format demote must clear sticky,
        not bring the PDF fence back (055).
        """
        if has_turn_attachments:
            return AttachmentRehydrateDecision(reason="already_fenced")
        kind = str(continuation_kind)
        file_bound = trust_prior_for_workers and (kind == "format" or (kind == "answer" and refers_to_prior))
        if not file_bound:
            # New topic / social / creative / demoted false format — drop sticky.
            return AttachmentRehydrateDecision(
                clear_pending=True,
                reason=f"clear_pending:{kind}",
            )
        ids = cls.attachment_ids_for_prior(dialog, prior_context=prior_context)
        if not ids:
            return AttachmentRehydrateDecision(reason="no_dialog_attachment_refs")
        return AttachmentRehydrateDecision(
            attachment_ids=ids,
            clear_pending=False,
            reason="rehydrate_prior_attachments",
        )

    @classmethod
    def attachment_ids_for_prior(
        cls,
        dialog: DialogTurnWindow | None,
        *,
        prior_context: str | None,
    ) -> tuple[UUID, ...]:
        """Resolve attachment UUIDs from the user turn that produced the prior."""
        if dialog is None or not dialog.turns:
            return ()
        turns = dialog.turns
        needle = (prior_context or "").strip()[:120]
        if needle:
            matched = _ids_before_assistant_containing(turns, needle)
            if matched:
                return matched
        return _ids_before_last_assistant(turns)


def _user_attachment_ids_before(
    turns: tuple[DialogTurn, ...],
    before_idx: int,
) -> tuple[UUID, ...]:
    from palatium_ai.domain.memory.turns import parse_turn_attachment_ids

    for j in range(before_idx - 1, -1, -1):
        turn = turns[j]
        if turn.role != "user":
            continue
        ids = parse_turn_attachment_ids(turn.payload)
        if ids:
            return ids
    return ()


def _ids_before_assistant_containing(
    turns: tuple[DialogTurn, ...],
    needle: str,
) -> tuple[UUID, ...]:
    for idx, turn in enumerate(turns):
        if turn.role != "assistant" or needle not in turn.content:
            continue
        return _user_attachment_ids_before(turns, idx)
    return ()


def _ids_before_last_assistant(turns: tuple[DialogTurn, ...]) -> tuple[UUID, ...]:
    last_asst: int | None = None
    for idx in range(len(turns) - 1, -1, -1):
        if turns[idx].role == "assistant":
            last_asst = idx
            break
    if last_asst is None:
        return ()
    return _user_attachment_ids_before(turns, last_asst)
