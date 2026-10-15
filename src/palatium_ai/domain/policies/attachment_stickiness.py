# src/palatium_ai/domain/policies/attachment_stickiness.py

"""When session sticky attachments may fence the current turn (Super Brain SB1/SB2).

Sticky ``pending_attachment_ids`` must not poison every follow-up: Continuity clears
dialog prior whenever ``untrusted_context`` is non-empty, which stuck the model on
the last upload (webp) and hid earlier document context.

Rules (structural, no phrase lists — 055):
- Explicit upload ids always fence.
- Session pending is NOT auto-restored into the fence at turn start.
- Mid-graph rehydrate only when Continuity ``trust_prior_for_workers`` and
  format / answer+refers_to_prior, and the Continuity needle binds a turn:
  ``answer`` → a **user** turn with the ids; ``format`` → the assistant turn that
  produced the prior. Assistant-only mention is never a bind for ``answer``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.grounding import GroundingPolicy
from palatium_ai.domain.policies.types import GROUNDING_DEFAULT

if TYPE_CHECKING:
    from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
    from palatium_ai.domain.policies.types import ContinuationKind, GroundingMode

RehydrateSource = Literal["user_prior", "message_binding", "none"]


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
    rehydrate_source: RehydrateSource = "none"


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
        grounding: GroundingMode | str | None = GROUNDING_DEFAULT,
        adaptive_grounding_enabled: bool = False,
    ) -> AttachmentRehydrateDecision:
        """After Continuity: optionally re-fence dialog-bound attachments for format.

        Rehydrate only when Continuity trusted prior for workers — a bare
        ``continuation_kind=format`` after false-format demote must clear sticky,
        not bring the PDF fence back (055).
        """
        if has_turn_attachments:
            return AttachmentRehydrateDecision(reason="already_fenced", rehydrate_source="none")
        if not GroundingPolicy.allows_sticky_attachment_rehydrate(
            enabled=adaptive_grounding_enabled,
            grounding=grounding,
        ):
            # Keep pending for a later format path; do not fence this required turn.
            return AttachmentRehydrateDecision(
                reason="grounding_required_skip_rehydrate",
                rehydrate_source="none",
            )
        kind = str(continuation_kind)
        file_bound = trust_prior_for_workers and (kind == "format" or (kind == "answer" and refers_to_prior))
        if not file_bound:
            # New topic / social / creative / demoted false format — drop sticky.
            return AttachmentRehydrateDecision(
                clear_pending=True,
                reason=f"clear_pending:{kind}",
                rehydrate_source="none",
            )
        ids, source = cls.attachment_ids_for_prior(
            dialog,
            prior_context=prior_context,
            continuation_kind=kind,
        )
        if not ids:
            return AttachmentRehydrateDecision(
                reason="no_dialog_attachment_refs",
                rehydrate_source=source,
            )
        return AttachmentRehydrateDecision(
            attachment_ids=ids,
            clear_pending=False,
            reason="rehydrate_prior_attachments",
            rehydrate_source=source,
        )

    @classmethod
    def attachment_ids_for_prior(
        cls,
        dialog: DialogTurnWindow | None,
        *,
        prior_context: str | None,
        continuation_kind: ContinuationKind | str = "answer",
    ) -> tuple[tuple[UUID, ...], RehydrateSource]:
        """Resolve attachment UUIDs bound to the Continuity prior — never the «newest upload».

        Binding rules (055 — structural, no phrase lists):
        - ``answer``: only a **user** turn carrying the ids may bind. An assistant
          mention is not evidence the user is asking about that file (cross-turn leak).
        - ``format``: the prior *is* the assistant content being transformed, so the
          upload from the user turn that produced it is a legitimate bind.
        No fallback to «attachments before the last assistant» — that re-fenced the
        newest upload whenever the prior failed to match.
        """
        if dialog is None or not dialog.turns:
            return (), "none"
        needle = (prior_context or "").strip()[:120]
        if not needle:
            return (), "none"
        user_ids = _ids_from_user_turn_containing(dialog.turns, needle)
        if user_ids:
            return user_ids, "user_prior"
        if str(continuation_kind) == "format":
            turn_ids = _ids_before_assistant_containing(dialog.turns, needle)
            if turn_ids:
                return turn_ids, "message_binding"
        return (), "none"


def _ids_from_user_turn_containing(
    turns: tuple[DialogTurn, ...],
    needle: str,
) -> tuple[UUID, ...]:
    """Most recent user turn containing needle and carrying attachment payload ids."""
    from palatium_ai.domain.memory.turns import parse_turn_attachment_ids

    for idx in range(len(turns) - 1, -1, -1):
        turn = turns[idx]
        if turn.role != "user":
            continue
        if needle not in turn.content:
            continue
        ids = parse_turn_attachment_ids(turn.payload)
        if ids:
            return ids
    return ()


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
    """Uploads from the user turn that produced the assistant content matching needle."""
    for idx in range(len(turns) - 1, -1, -1):
        turn = turns[idx]
        if turn.role != "assistant" or needle not in turn.content:
            continue
        return _user_attachment_ids_before(turns, idx)
    return ()
