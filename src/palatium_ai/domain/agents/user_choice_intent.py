"""Normalize Intent exclusive-choice axis (code > LLM prose).

When the classifier marks requires_user_choice (or user_choice/select caps),
the turn's job is a menu / discrete pick — not a knowledge dump. Remap
knowledge_request / social into clarification_needed here so Supervisor
routes clarify even before Continuity runs.

Does not use phrase lists. Does not invent choice when the flag is absent
(structural force-mint after Formatter covers menu-shaped documents).
"""

from __future__ import annotations

from palatium_ai.domain.agents.intent import IntentClassifierOutput, TaskKind

_CHOICE_REMAP_KINDS: frozenset[TaskKind] = frozenset(
    {
        "knowledge_request",
        "social_conversation",
    }
)


class UserChoiceIntentPolicy:
    """Pure domain: IntentClassifierOutput → choice-normalized IntentClassifierOutput."""

    @classmethod
    def normalize(cls, output: IntentClassifierOutput) -> IntentClassifierOutput:
        """Ensure choice axis is coherent for routing + HITL."""
        _ = cls
        caps = tuple(output.candidate_capabilities)
        cap_set = {item.strip().lower() for item in caps}
        requires_user_choice = bool(output.requires_user_choice) or "user_choice" in cap_set or "select" in cap_set

        if requires_user_choice and "user_choice" not in cap_set:
            caps = (*caps, "user_choice")

        task_kind = output.task_kind
        requires_mcp = output.requires_mcp
        reasoning = output.reasoning

        if requires_user_choice and task_kind in _CHOICE_REMAP_KINDS:
            task_kind = "clarification_needed"
            requires_mcp = False
            reasoning = f"{reasoning}; user_choice_policy → clarification_needed"

        if (
            requires_user_choice == output.requires_user_choice
            and task_kind == output.task_kind
            and requires_mcp == output.requires_mcp
            and caps == output.candidate_capabilities
            and reasoning == output.reasoning
        ):
            return output

        return output.model_copy(
            update={
                "task_kind": task_kind,
                "requires_mcp": requires_mcp,
                "requires_user_choice": requires_user_choice,
                "candidate_capabilities": caps,
                "reasoning": reasoning[:2000],
            }
        )
