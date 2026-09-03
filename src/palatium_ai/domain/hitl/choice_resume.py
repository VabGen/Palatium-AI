# src/palatium_ai/domain/hitl/choice_resume.py

"""Server-bound resume for user_choice cards (never free-text process(label))."""

from __future__ import annotations

import re

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.content import ActionKind
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption
from palatium_ai.domain.policies.types import ContinuationKind

# Typed resume axes — Intent/Contextualizer route on these, not NL prose.
HitlChoiceResumeKind = Literal["format", "tool", "clarify"]

_HITL_LABEL_CLOSE = "<<<END_UNTRUSTED_HITL_LABEL>>>"
_RESUME_HEADER_RE = re.compile(
    r"<<<HITL_CHOICE_RESUME\s+kind=(?P<kind>format|tool|clarify)\s+"
    r"action_id=(?P<action_id>[^\s>]+)\s+"
    r"option_kind=(?P<option_kind>[^\s>]+)\s*>>>",
    re.MULTILINE,
)
_LABEL_BLOCK_RE = re.compile(
    rf"<<<UNTRUSTED_HITL_LABEL\n(?P<label>.*?)\n{_HITL_LABEL_CLOSE}",
    re.DOTALL,
)
_REWRITE_MAX = 4000
_PRIOR_USER_MAX = 2000


class HitlChoiceSelection(BaseModel):
    """Authoritative option picked from a server-minted card."""

    model_config = {"frozen": True}

    action_id: str = Field(min_length=1, max_length=120)
    label: str = Field(min_length=1, max_length=200)
    resume_kind: HitlChoiceResumeKind
    option_kind: ActionKind = "custom"


class ParsedHitlChoiceResume(BaseModel):
    """Parsed machine envelope from graph_user_text (no LLM)."""

    model_config = {"frozen": True}

    resume_kind: HitlChoiceResumeKind
    action_id: str = Field(min_length=1, max_length=120)
    option_kind: str = Field(min_length=1, max_length=40)
    label: str = Field(min_length=1, max_length=200)


class ChoiceResumePolicy:
    """Map card + action_id → typed resume envelope (no NL instructions)."""

    @classmethod
    def resume_kind_for(cls, option: HITLOption) -> HitlChoiceResumeKind:
        """Derive resume axis from ActionKind — never from label text."""
        _ = cls
        if option.kind == "format":
            return "format"
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
        Fence-close markers inside the label are neutralized (same contract as tool output).
        """
        _ = cls
        safe_label = selection.label.replace(_HITL_LABEL_CLOSE, "[redacted-end-fence]")
        return (
            f"<<<HITL_CHOICE_RESUME kind={selection.resume_kind} "
            f"action_id={selection.action_id} option_kind={selection.option_kind}>>>\n"
            f"<<<UNTRUSTED_HITL_LABEL\n{safe_label}\n{_HITL_LABEL_CLOSE}"
        )

    @classmethod
    def try_parse_graph_user_text(cls, text: str) -> ParsedHitlChoiceResume | None:
        """Parse typed resume envelope; None if not a HITL choice turn."""
        _ = cls
        stripped = text.strip()
        header = _RESUME_HEADER_RE.search(stripped)
        if header is None:
            return None
        label_match = _LABEL_BLOCK_RE.search(stripped)
        if label_match is None:
            return None
        label = label_match.group("label").strip()
        if not label:
            return None
        kind = header.group("kind")
        if kind not in {"format", "tool", "clarify"}:
            return None
        return ParsedHitlChoiceResume(
            resume_kind=kind,  # type: ignore[arg-type]
            action_id=header.group("action_id")[:120],
            option_kind=header.group("option_kind")[:40],
            label=label[:200],
        )

    @classmethod
    def continuation_kind_for(cls, resume_kind: HitlChoiceResumeKind) -> ContinuationKind:
        """Map envelope resume_kind → Contextualizer continuation_kind (055).

        Envelope kind=clarify means 'pick from a clarify menu', not 'still ambiguous'.
        That completes the discrete slot → answer (or format) with refers_to_prior.
        """
        _ = cls
        if resume_kind == "format":
            return "format"
        return "answer"

    @classmethod
    def rewrite_query_for_resume(
        cls,
        *,
        parsed: ParsedHitlChoiceResume,
        prior_user_text: str | None,
        prior_assistant_excerpt: str | None,
    ) -> str:
        """Self-contained ask: prior user goal + selected slot value (label is data only)."""
        _ = cls
        label = parsed.label.strip()
        prior_user = (prior_user_text or "").strip()
        if prior_user and "HITL_CHOICE_RESUME" not in prior_user:
            base = prior_user[:_PRIOR_USER_MAX]
            rewritten = f"{base}\n[selected_option action_id={parsed.action_id}] {label}"
        elif prior_assistant_excerpt and prior_assistant_excerpt.strip():
            excerpt = prior_assistant_excerpt.strip()[:_PRIOR_USER_MAX]
            rewritten = (
                f"Continue the prior assistant clarification using the selected option.\n"
                f"Prior:\n{excerpt}\n"
                f"[selected_option action_id={parsed.action_id}] {label}"
            )
        else:
            rewritten = f"[selected_option action_id={parsed.action_id}] {label}"
        return rewritten[:_REWRITE_MAX]


def hitl_card_public_dump(card: HITLCardView) -> dict[str, object]:
    """Serialize card for dialog history without capability tokens."""
    return card.without_secrets().model_dump(mode="json")
