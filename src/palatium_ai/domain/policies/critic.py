# src/palatium_ai/domain/policies/critic.py

"""Critic gate policy — when LLM-as-a-Judge is required vs deterministic passthrough.

Authority for skipping Critic LLM on true reformatting / high-confidence clarify.
Fail-closed: tools, MCP, low confidence, answer-continuity, social routed as
``format_only``, or clarify with substantive user payload always invoke the judge.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.tool_output import contains_untrusted_tool_output
from palatium_ai.domain.policies.types import ExecutionStrategy, TaskKind

# User turn long enough to be a payload (document / detailed ask), not a phatic ping.
_SUBSTANTIVE_USER_CHARS = 400
_HIGH_CONFIDENCE_STRATEGIES = frozenset({"reason_only", "retrieve_then_reason", "data_analysis", "code_sandbox"})


class CriticGateDecision(BaseModel):
    """Outcome of CriticPolicy for one turn."""

    model_config = {"frozen": True}

    invoke_llm: bool
    reason: str = Field(min_length=1, max_length=128)


def _invoke(reason: str) -> CriticGateDecision:
    return CriticGateDecision(invoke_llm=True, reason=reason)


def _passthrough(reason: str) -> CriticGateDecision:
    return CriticGateDecision(invoke_llm=False, reason=reason)


class CriticPolicy:
    """Pure domain policy: strategy + confidence → Critic LLM or passthrough."""

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
        worker_confidence: float | None = None,
        has_attachment_context: bool = False,
    ) -> CriticGateDecision:
        """Return whether Critic must call an LLM (fail-closed on risk signals)."""
        hard = cls._hard_risk_gate(
            requires_mcp=requires_mcp,
            requires_tool_call=requires_tool_call,
            worker_summary=worker_summary,
            has_attachment_context=has_attachment_context,
        )
        if hard is not None:
            return hard

        route = cls._route_gate(
            selected_strategy=selected_strategy,
            task_kind=task_kind,
            continuation_kind=continuation_kind,
            classification_confidence=classification_confidence,
            confidence_threshold=confidence_threshold,
            user_input_chars=user_input_chars,
            worker_summary=worker_summary,
        )
        if route is not None:
            return route

        if cls._high_confidence_passthrough(
            selected_strategy=selected_strategy,
            continuation_kind=continuation_kind,
            confidence_threshold=confidence_threshold,
            requires_mcp=requires_mcp,
            requires_tool_call=requires_tool_call,
            worker_confidence=worker_confidence,
        ):
            return _passthrough("high_worker_confidence_passthrough")

        return _invoke("default_quality_gate")

    @staticmethod
    def _hard_risk_gate(
        *,
        requires_mcp: bool,
        requires_tool_call: bool,
        worker_summary: str | None,
        has_attachment_context: bool,
    ) -> CriticGateDecision | None:
        if requires_tool_call or requires_mcp:
            return _invoke("side_effect_risk")
        if contains_untrusted_tool_output(worker_summary):
            return _invoke("untrusted_tool_evidence")
        # Fenced upload: judge must verify grounding (no prior-file echo).
        if has_attachment_context:
            return _invoke("attachment_grounding_gate")
        return None

    @staticmethod
    def _route_gate(
        *,
        selected_strategy: ExecutionStrategy,
        task_kind: TaskKind,
        continuation_kind: str | None,
        classification_confidence: float,
        confidence_threshold: float,
        user_input_chars: int,
        worker_summary: str | None,
    ) -> CriticGateDecision | None:
        # True reformatting of prior content — not social routed as format_only (2026).
        if continuation_kind == "format" or task_kind == "response_formatting":
            if worker_summary and worker_summary.strip():
                return _passthrough("format_passthrough")
            return _invoke("format_without_source")

        # Answer follow-ups must not skip the judge (history-blind clarify risk).
        if continuation_kind == "answer":
            return _invoke("answer_continuity_gate")

        # Clarify while user already sent a substantive payload → likely wrong route.
        clarifying = selected_strategy == "clarify" or task_kind == "clarification_needed"
        if clarifying and user_input_chars >= _SUBSTANTIVE_USER_CHARS:
            return _invoke("clarify_with_substantive_input")

        if selected_strategy == "clarify":
            if classification_confidence >= confidence_threshold:
                return _passthrough("clarify_passthrough")
            return _invoke("low_confidence")
        return None

    @staticmethod
    def _high_confidence_passthrough(
        *,
        selected_strategy: ExecutionStrategy,
        continuation_kind: str | None,
        confidence_threshold: float,
        requires_mcp: bool,
        requires_tool_call: bool,
        worker_confidence: float | None,
    ) -> bool:
        # P1.7: high-confidence worker draft without side effects — skip frontier/mid judge.
        return (
            selected_strategy in _HIGH_CONFIDENCE_STRATEGIES
            and worker_confidence is not None
            and worker_confidence >= confidence_threshold
            and not requires_mcp
            and not requires_tool_call
            and continuation_kind not in {"answer", "clarify"}
        )
