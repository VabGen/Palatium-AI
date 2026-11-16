# src/palatium_ai/domain/policies/attachment_focus.py

"""Whether the turn's uploads belong in the prompt at all (Intent Guard, 055).

The fence is injected into every prompt from one funnel
(``selectors._with_untrusted_context``); without a gate, a chitchat or memory turn
carries a whole contract into the model and the next answer can quote it
(«context bleed»). The decision is taken from typed intent axes — never from a
phrase list — and defaults to *include*, because withholding evidence the model
needed is the more dangerous error (it answers from invention instead).

Pure and deterministic: no I/O, no LLM, unit-testable on all axis pairs.
"""

from __future__ import annotations

from palatium_ai.domain.policies.types import AttachmentFocus, TaskKind

#: Task kinds whose answer is never grounded in the turn's files: the user is
#: greeting, thanking, or the ask is itself a request to disambiguate. Even a
#: mislabelled ``attachment_focus`` cannot put a document into these prompts.
_NON_FILE_TASK_KINDS: frozenset[str] = frozenset({"social_conversation", "clarification_needed"})


class AttachmentPromptPolicy:
    """Typed axes → whether the fenced uploads are part of this turn's prompt."""

    @staticmethod
    def includes_uploads(*, task_kind: TaskKind, focus: AttachmentFocus) -> bool:
        """False when the ask explicitly disowns the uploads or cannot target them."""
        if task_kind in _NON_FILE_TASK_KINDS:
            return False
        return focus != "none"

    @staticmethod
    def detach_reason(*, task_kind: TaskKind, focus: AttachmentFocus) -> str:
        """Observable reason for the withheld fence (logged, never user-facing)."""
        if task_kind in _NON_FILE_TASK_KINDS:
            return f"task_kind={task_kind}"
        if focus == "none":
            return "attachment_focus=none"
        return "attached"


__all__ = ["AttachmentPromptPolicy"]
