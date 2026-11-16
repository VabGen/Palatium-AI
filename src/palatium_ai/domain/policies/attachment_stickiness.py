# src/palatium_ai/domain/policies/attachment_stickiness.py

"""When session sticky attachments may fence the current turn (Super Brain SB1/SB2).

Sticky ``pending_attachment_ids`` must not poison every follow-up: Continuity clears
dialog prior whenever ``untrusted_context`` is non-empty, which stuck the model on
the last upload (webp) and hid earlier document context.

Rules (structural, no phrase lists — 055):
- Explicit upload ids always fence.
- Session pending is NOT auto-restored into the fence at turn start.
- Mid-graph rehydrate only when Continuity ``trust_prior_for_workers`` and
  format / answer+refers_to_prior:
  ``answer`` → only a **user** turn containing the Continuity needle may bind;
  ``format`` → the assistant turn the needle identifies, else the answer the request
  immediately follows (positional last resort). Assistant-only mention is never a
  bind for ``answer``; session pending never binds either kind.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.grounding import GroundingPolicy
from palatium_ai.domain.policies.transform import TransformPolicy
from palatium_ai.domain.policies.types import GROUNDING_DEFAULT, TRANSFORMATION_DEFAULT

if TYPE_CHECKING:
    from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
    from palatium_ai.domain.policies.types import ContinuationKind, GroundingMode, TransformationKind

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
        transformation: TransformationKind | str = TRANSFORMATION_DEFAULT,
    ) -> AttachmentRehydrateDecision:
        """After Continuity: optionally re-fence dialog-bound attachments for format.

        Rehydrate only when Continuity trusted prior for workers — a bare
        ``continuation_kind=format`` after false-format demote must clear sticky,
        not bring the PDF fence back (055).

        A content transform (expand / shorten / rewrite) is answered from the prior
        **text**, not from its source file: fencing the last turn's upload lets the
        worker re-analyse that document and lose the ask ("перепиши ответ короче"
        turned into "сравнение файлов"). The transformation axis therefore wins over
        the positional bind (055).
        """
        if has_turn_attachments:
            return AttachmentRehydrateDecision(reason="already_fenced", rehydrate_source="none")
        if TransformPolicy.needs_reason_over_prior(transformation):
            # The prior assistant answer IS the source. Keep no fence: an attachment
            # would re-open a topic the transform must not answer.
            return AttachmentRehydrateDecision(
                clear_pending=True,
                reason="clear_pending:transform_over_prior",
                rehydrate_source="none",
            )
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
    def thread_has_files(cls, dialog: DialogTurnWindow | None) -> bool:
        """True when any dialog turn carries uploaded attachment payload ids.

        Structural precondition for the Intent ``file_reference`` axis: a storage
        re-read can only target a file the thread actually holds (055). Reads the same
        turn payloads the fence binds from — one definition of «thread file».
        """
        if dialog is None:
            return False
        from palatium_ai.domain.memory.turns import parse_turn_attachment_ids

        return any(parse_turn_attachment_ids(turn.payload) for turn in dialog.turns)

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
        - ``answer``: a **user** turn carrying the ids may bind by needle. Otherwise the
          bind is the upload set of the user turn the last assistant answer directly
          follows, when the needle identifies that answer's own content: a follow-up
          continues the last answer, so its evidence turn is the file set — with two
          candidates a *per-file* choice would be a guess, the set is not. Strictly
          adjacent: an answer preceded by a text-only user turn binds nothing, so an
          older unrelated upload is never resurrected (cross-turn leak). The last safe
          case stays a **single-file thread** — there is no other file to bind
          (P0 sticky-context contract).
        - ``format``: the prior *is* the assistant answer being transformed. First the
          assistant turn that the excerpt identifies; when the excerpt is a paraphrase
          and identifies no turn, the last-resort bind is the answer the request
          immediately follows (positional, thread-scoped ids only).
          Foreign / stale ids are rejected downstream by thread-scoped resolution.
        Session pending is never a bind source for either kind.
        """
        if dialog is None or not dialog.turns:
            return (), "none"
        needle = (prior_context or "").strip()[:120]
        if not needle:
            return (), "none"
        if str(continuation_kind) == "format":
            bound = _ids_before_assistant_containing(dialog.turns, needle)
            if bound:
                return bound, "message_binding"
            last_answer = _ids_from_last_assistant_uploads(dialog.turns)
            if last_answer:
                return last_answer, "message_binding"
            return (), "none"
        user_ids = _ids_from_user_turn_containing(dialog.turns, needle)
        if user_ids:
            return user_ids, "user_prior"
        answer_ids = _ids_from_continued_answer_uploads(dialog.turns, needle=needle)
        if answer_ids:
            return answer_ids, "message_binding"
        only_file = _single_thread_attachment(dialog.turns)
        if only_file:
            return only_file, "message_binding"
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


def _ids_from_continued_answer_uploads(
    turns: tuple[DialogTurn, ...],
    *,
    needle: str,
) -> tuple[UUID, ...]:
    """Uploads of the user turn the last assistant answer directly follows.

    ``answer`` continues the last answer, so when the Continuity needle identifies
    that answer's content, its upload set is the evidence being continued — keeping
    a multi-file thread bound instead of dropping to no fence. Strictly adjacent:
    a text-only user turn before the answer binds nothing (no stale resurrection),
    and a needle matching an *older* answer binds nothing either (that answer is not
    the one the follow-up continues).
    """
    from palatium_ai.domain.memory.turns import parse_turn_attachment_ids

    for idx in range(len(turns) - 1, -1, -1):
        if turns[idx].role != "assistant":
            continue
        if needle not in turns[idx].content:
            return ()
        if idx == 0 or turns[idx - 1].role != "user":
            return ()
        return parse_turn_attachment_ids(turns[idx - 1].payload)
    return ()


def _ids_from_last_assistant_uploads(
    turns: tuple[DialogTurn, ...],
) -> tuple[UUID, ...]:
    """Uploads of the user turn that produced the last assistant answer.

    Last-resort ``format`` bind, used only when the excerpt identifies no assistant
    turn (LLM paraphrase). Positional, never pending; foreign ids are filtered
    downstream by thread-scoped resolution.
    """
    for idx in range(len(turns) - 1, -1, -1):
        if turns[idx].role == "assistant":
            return _user_attachment_ids_before(turns, idx)
    return ()


def _single_thread_attachment(turns: tuple[DialogTurn, ...]) -> tuple[UUID, ...]:
    """The thread's only uploaded file, when it has exactly one.

    P0 sticky-context contract: an ``answer`` follow-up must not lose the file it is
    about. With a single candidate the choice is unambiguous, so a paraphrase of the
    prior answer is enough — there is no other file the fence could pick. Two or more
    candidates keep the strict user-turn bind, because a paraphrase cannot tell the
    answer's source from a file merely mentioned in it (cross-turn leak).
    """
    from palatium_ai.domain.memory.turns import parse_turn_attachment_ids

    distinct: set[UUID] = set()
    for turn in turns:
        distinct.update(parse_turn_attachment_ids(turn.payload))
        if len(distinct) > 1:
            return ()
    return tuple(distinct) if len(distinct) == 1 else ()


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
