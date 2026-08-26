# src/palatium_ai/domain/hitl/choice_resume.py

"""Server-bound resume for user_choice cards (never free-text process(label))."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.content import ActionKind
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption

# Typed resume axes — Intent/Contextualizer route on these, not NL prose.
HitlChoiceResumeKind = Literal["format", "tool", "clarify"]


class HitlChoiceSelection(BaseModel):
    """Authoritative option picked from a server-minted card."""

    model_config = {"frozen": True}

    action_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    resume_kind: HitlChoiceResumeKind
    option_kind: ActionKind = "custom"


class ChoiceResumePolicy:
    """Map card + action_id → typed resume envelope (no NL instructions)."""

    @classmethod
    def resume_kind_for(cls, option: HITLOption) -> HitlChoiceResumeKind:
        """Derive resume axis from ActionKind — never from label text."""
        _ = cls
        if option.kind in {"approve", "confirm"}:
            return "tool"
        if option.kind in {"reject", "dismiss"}:
            return "clarify"
        # custom menu picks (clarification / analysis type): continue clarify→answer path
        return "clarify"

    @classmethod
    def selection_from_card(cls, card: HITLCardView, action_id: str) -> HitlChoiceSelection:
        """Resolve option solely by action_id (server registry)."""
        for option in card.options:
            if option.action_id == action_id:
                return HitlChoiceSelection(
                    action_id=option.action_id,
                    label=option.label,
                    resume_kind=cls.resume_kind_for(option),
                    option_kind=option.kind,
                )
        raise ValueError(f"action_id '{action_id}' is not on card {card.card_id}")

    @classmethod
    def graph_user_text(cls, selection: HitlChoiceSelection) -> str:
        """Machine envelope only — no natural-language instructions for the graph.

        Label is fenced untrusted display data. Agents must route on resume_kind + action_id.
        """
        _ = cls
        return (
            f"<<<HITL_CHOICE_RESUME kind={selection.resume_kind} "
            f"action_id={selection.action_id} option_kind={selection.option_kind}>>>\n"
            f"<<<UNTRUSTED_HITL_LABEL\n{selection.label}\n<<<END_UNTRUSTED_HITL_LABEL>>>"
        )


def hitl_card_public_dump(card: HITLCardView) -> dict[str, object]:
    """Serialize card for dialog history without capability tokens."""
    return card.without_secrets().model_dump(mode="json")
