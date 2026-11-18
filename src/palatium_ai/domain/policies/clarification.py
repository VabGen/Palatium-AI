# src/palatium_ai/domain/policies/clarification.py

"""When a turn may stop at a clarification instead of answering (055).

Clarification is the exception, not the default (Copilot / Gemini / ChatGPT 2026):
if the assistant can produce a reasonable answer — or an honest no-data — it
answers. A clarify outcome is admitted only when ALL hold:

1. the classifier named *what* is missing (``underspecification_kind != "none"``
   or an explicit exclusive-choice deliverable), and
2. the label is confident (``confidence >= CLARIFY_MIN_CONFIDENCE``), and
3. the gap is a *product slot* with thread evidence (prior dialog / attachment),
   not bare world-knowledge entity polysemy («какой протокол у Зенита?» with an
   empty thread → answer / no-data, not a «который Зенит?» menu — W10 P1.3).

Otherwise the turn falls back to ``knowledge_request``. Unknown / failed
classification lands here too, so an LLM hiccup never surfaces as a HITL card.
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
        has_prior_dialog: bool = False,
        has_attachment_context: bool = False,
        user_text: str = "",
    ) -> IntentClassifierOutput:
        """Return ``output`` unchanged, or demoted to the default answer path."""
        if output.task_kind == "knowledge_request":
            return cls._require_evidence_for_empty_thread_fact(
                output,
                has_prior_dialog=has_prior_dialog,
                has_attachment_context=has_attachment_context,
                user_text=user_text,
            )
        if output.task_kind != "clarification_needed":
            return output
        if not cls.is_justified(output, min_confidence=min_confidence):
            return cls._demote(
                output,
                gate_reason=(f"underspec={output.underspecification_kind}, confidence={output.confidence:.2f}"),
                grounding=output.grounding,
                requires_mcp=False,
            )
        if cls.is_ungrounded_entity_disambiguation(
            output,
            has_prior_dialog=has_prior_dialog,
            has_attachment_context=has_attachment_context,
            user_text=user_text,
        ):
            # Fact ask + empty thread: retrieve then honest no-data (grounding required).
            # requires_mcp must stay True — otherwise reason_only invents world knowledge
            # and never hits the empty-retrieval «нет данных» path (W10 3b).
            return cls._demote(
                output,
                gate_reason="ungrounded_entity_disambiguation",
                grounding="required",
                requires_mcp=True,
            )
        return output

    @classmethod
    def _require_evidence_for_empty_thread_fact(
        cls,
        output: IntentClassifierOutput,
        *,
        has_prior_dialog: bool,
        has_attachment_context: bool,
        user_text: str,
    ) -> IntentClassifierOutput:
        """Bump optional grounding → required when an empty thread asks a fact question.

        Compose/draft/none stays untouched (jokes, generation). Optional fact asks with
        no prior/attachments must retrieve then refuse — not invent (W10 3b).
        """
        if has_prior_dialog or has_attachment_context:
            return output
        # Intent often marks fact asks as grounding=none («general knowledge») —
        # that must still retrieve→refuse, not invent (W10 3b). Compose stays none.
        if output.grounding == "required":
            return output
        if not cls._looks_like_fact_ask(output, user_text=user_text):
            return output
        caps = {c.strip().lower() for c in output.candidate_capabilities}
        if caps & {"compose", "draft", "format", "expand", "shorten", "rewrite"}:
            return output
        reason = f"{output.reasoning}; clarification_gate → grounding=required (empty_thread_fact)"
        return output.model_copy(
            update={
                "grounding": "required",
                "requires_mcp": True,
                "grounding_reason": "empty_thread_fact_ask",
                "reasoning": reason[:2000],
            }
        )

    @classmethod
    def is_ungrounded_entity_disambiguation(
        cls,
        output: IntentClassifierOutput,
        *,
        has_prior_dialog: bool,
        has_attachment_context: bool,
        user_text: str,
    ) -> bool:
        """Discrete-choice clarify with no thread evidence on a complete fact ask.

        Without prior/attachments there is nothing to offer as clickable product
        options — only a world-knowledge guess about what a name means. Big Tech
        answers (or says no data) instead of inventing a disambiguation menu.
        """
        if has_prior_dialog or has_attachment_context:
            return False
        if output.underspecification_kind != "discrete_choice" and not output.requires_user_choice:
            return False
        # Axis-driven: a complete fact ask on an empty thread is not a product-slot
        # menu. Punctuation (``?``) is not a router (055).
        return cls._looks_like_fact_ask(output, user_text=user_text)

    @staticmethod
    def _looks_like_fact_ask(output: IntentClassifierOutput, *, user_text: str) -> bool:
        """True when axes say this is a grounded knowledge ask, not compose/format.

        Uses Intent axes only — never surface heuristics like ``endswith("?")``.
        """
        ask = user_text.strip()
        if not ask:
            return False
        caps = {c.strip().lower() for c in output.candidate_capabilities}
        if caps & {"compose", "draft", "format", "expand", "shorten", "rewrite"}:
            return False
        if output.grounding in {"required", "optional"}:
            return True
        if output.task_kind in {"knowledge_request", "tool_execution", "clarification_needed"}:
            return bool(caps & {"retrieve", "search", "knowledge", "user_choice"}) or (
                output.underspecification_kind == "discrete_choice" or output.requires_user_choice
            )
        return False

    @classmethod
    def _demote(
        cls,
        output: IntentClassifierOutput,
        *,
        gate_reason: str,
        grounding: str,
        requires_mcp: bool,
    ) -> IntentClassifierOutput:
        caps = tuple(c for c in output.candidate_capabilities if c.strip().lower() != "user_choice")
        reason = f"{output.reasoning}; clarification_gate → knowledge_request ({gate_reason})"
        return output.model_copy(
            update={
                "task_kind": "knowledge_request",
                "requires_mcp": requires_mcp,
                "requires_user_choice": False,
                "underspecification_kind": "none",
                "grounding": grounding,
                "candidate_capabilities": caps,
                "reasoning": reason[:2000],
            }
        )
