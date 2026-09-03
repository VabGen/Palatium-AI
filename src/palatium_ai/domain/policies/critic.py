# src/palatium_ai/domain/policies/critic.py

"""Critic gate policy — when LLM-as-a-Judge is required vs deterministic passthrough.

Authority for skipping Critic LLM on low-risk strategies (format / ack / high-confidence
clarify). Fail-closed: tools, MCP, low confidence, answer-continuity, or clarify with
substantive user payload always invoke the judge.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.tool_output import contains_untrusted_tool_output
from palatium_ai.domain.policies.types import ExecutionStrategy, TaskKind

# User turn long enough to be a payload (document / detailed ask), not a phatic ping.
_SUBSTANTIVE_USER_CHARS = 400


class CriticGateDecision(BaseModel):
    """Outcome of CriticPolicy for one turn."""

    model_config = {"frozen": True}

    invoke_llm: bool
    reason: str = Field(min_length=1, max_length=128)


class CriticPolicy:
    """Pure domain policy: strategy + confidence → Critic LLM or passthrough."""

    _FORMAT_STRATEGIES: frozenset[str] = frozenset({"format_only"})
    _DIRECT_REPLY_STRATEGIES: frozenset[str] = frozenset({"ack_only", "clarify"})

    @classmethod
    def decide(
        cls,
        *,
        selected_strategy: ExecutionStrategy,
        task_kind: TaskKind,
        continuation_kind: str | None,
        classification_confidence: float,
        confidence_threshold: float,
        requires_mcp: bool,
        requires_tool_call: bool,
        worker_summary: str | None,
        user_input_chars: int = 0,
    ) -> CriticGateDecision:
        """Return whether Critic must call an LLM (fail-closed on risk signals)."""
        if requires_tool_call or requires_mcp:
            return CriticGateDecision(invoke_llm=True, reason="side_effect_risk")

        if contains_untrusted_tool_output(worker_summary):
            return CriticGateDecision(invoke_llm=True, reason="untrusted_tool_evidence")

        if (
            selected_strategy in cls._FORMAT_STRATEGIES
            or continuation_kind == "format"
            or task_kind == "response_formatting"
        ):
            if worker_summary and worker_summary.strip():
                return CriticGateDecision(invoke_llm=False, reason="format_passthrough")
            return CriticGateDecision(invoke_llm=True, reason="format_without_source")

        # Answer follow-ups must not skip the judge (history-blind clarify risk).
        if continuation_kind == "answer":
            return CriticGateDecision(invoke_llm=True, reason="answer_continuity_gate")

        # Clarify while user already sent a substantive payload → likely wrong route.
        if (
            selected_strategy == "clarify" or task_kind == "clarification_needed"
        ) and user_input_chars >= _SUBSTANTIVE_USER_CHARS:
            return CriticGateDecision(invoke_llm=True, reason="clarify_with_substantive_input")

        if selected_strategy in cls._DIRECT_REPLY_STRATEGIES or task_kind == "social_conversation":
            if classification_confidence >= confidence_threshold:
                return CriticGateDecision(
                    invoke_llm=False,
                    reason=f"{selected_strategy}_passthrough",
                )
            return CriticGateDecision(invoke_llm=True, reason="low_confidence")

        return CriticGateDecision(invoke_llm=True, reason="default_quality_gate")
