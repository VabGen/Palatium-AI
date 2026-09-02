"""Normalize Intent exclusive-choice + underspecification axes (code > LLM prose).

discrete_choice / requires_user_choice → clarification_needed (not knowledge dump).
open_text stays clarification without forcing HITL choice cards.
No phrase lists.
"""

from __future__ import annotations

from palatium_ai.domain.agents.intent import (
    IntentClassifierOutput,
    TaskKind,
    UnderspecificationKind,
)

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
        """Ensure choice / underspecification axes are coherent for routing + HITL."""
        _ = cls
        caps = tuple(output.candidate_capabilities)
        cap_set = {item.strip().lower() for item in caps}
        underspec: UnderspecificationKind = output.underspecification_kind
        requires_user_choice = (
            bool(output.requires_user_choice) or underspec == "discrete_choice" or "user_choice" in cap_set
        )

        if requires_user_choice and underspec == "none":
            underspec = "discrete_choice"
        if underspec == "open_text":
            # Free-form clarify — do not invent exclusive menus.
            requires_user_choice = False

        if requires_user_choice and "user_choice" not in cap_set:
            caps = (*caps, "user_choice")

        task_kind = output.task_kind
        requires_mcp = output.requires_mcp
        reasoning = output.reasoning

        if requires_user_choice and task_kind in _CHOICE_REMAP_KINDS:
            task_kind = "clarification_needed"
            requires_mcp = False
            reasoning = f"{reasoning}; user_choice_policy → clarification_needed"
        elif underspec == "open_text" and task_kind in _CHOICE_REMAP_KINDS:
            task_kind = "clarification_needed"
            requires_mcp = False
            reasoning = f"{reasoning}; open_text underspec → clarification_needed"

        if (
            requires_user_choice == output.requires_user_choice
            and underspec == output.underspecification_kind
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
                "underspecification_kind": underspec,
                "candidate_capabilities": caps,
                "reasoning": reasoning[:2000],
            }
        )
