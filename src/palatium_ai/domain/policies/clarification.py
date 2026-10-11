# src/palatium_ai/domain/policies/clarification.py

"""When a turn may stop at a clarification instead of answering (055).

Clarification is the exception, not the default (Copilot / Gemini 2026): if the
assistant can produce a reasonable answer, it answers. A clarify outcome is
admitted only when BOTH hold:

1. the classifier named *what* is missing (``underspecification_kind != "none"``
   or an explicit exclusive-choice deliverable), and
2. the label is confident (``confidence >= CLARIFY_MIN_CONFIDENCE``).

Otherwise the turn falls back to the default answer path (``knowledge_request``,
no MCP, no choice menu). Unknown / failed classification lands here too, so an
LLM hiccup never surfaces as a HITL card.
"""

from __future__ import annotations

from palatium_ai.domain.agents.intent import IntentClassifierOutput

# Same floor as AgentConfig.confidence_threshold default (030.7): below it a label
# is a guess, and a guessed clarify costs the user a round-trip.
CLARIFY_MIN_CONFIDENCE = 0.7


class ClarificationGatePolicy:
    """Pure policy: demote unjustified / low-confidence clarify to the answer path."""

    @staticmethod
    def is_justified(output: IntentClassifierOutput, *, min_confidence: float = CLARIFY_MIN_CONFIDENCE) -> bool:
        """True when ``clarification_needed`` is grounded in a named gap and confident."""
        if output.task_kind != "clarification_needed":
            return True
        names_gap = output.underspecification_kind != "none" or output.requires_user_choice
        return names_gap and output.confidence >= min_confidence

    @classmethod
    def apply(
        cls,
        output: IntentClassifierOutput,
        *,
        min_confidence: float = CLARIFY_MIN_CONFIDENCE,
    ) -> IntentClassifierOutput:
        """Return ``output`` unchanged, or demoted to the default answer path."""
        if cls.is_justified(output, min_confidence=min_confidence):
            return output
        caps = tuple(c for c in output.candidate_capabilities if c.strip().lower() != "user_choice")
        reason = (
            f"{output.reasoning}; clarification_gate → knowledge_request "
            f"(underspec={output.underspecification_kind}, confidence={output.confidence:.2f})"
        )
        return output.model_copy(
            update={
                "task_kind": "knowledge_request",
                "requires_mcp": False,
                "requires_user_choice": False,
                "underspecification_kind": "none",
                "candidate_capabilities": caps,
                "reasoning": reason[:2000],
            }
        )
