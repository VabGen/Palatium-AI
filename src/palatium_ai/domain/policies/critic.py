# src/palatium_ai/domain/policies/critic.py

"""Critic gate policy — when LLM-as-a-Judge is required vs deterministic passthrough.

Authority for skipping Critic LLM on true reformatting / high-confidence clarify /
phatic social (no worker draft). Fail-closed: tools, MCP, low confidence,
answer-continuity, or clarify with substantive user payload always invoke the judge.

2026 Big Tech: ChatGPT / Claude / Copilot do not mint quality HITL on greetings —
LLM-as-judge on ``social_conversation`` + ``format_only`` was producing false
``quality_review`` cards and identity self-attribution noise.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.tool_output import contains_untrusted_tool_output
from palatium_ai.domain.policies.types import (
    SUBSTANTIVE_USER_PAYLOAD_CHARS,
    ExecutionStrategy,
    ResolvedUncertaintyDisposition,
    TaskKind,
    UncertaintyDisposition,
)
from palatium_ai.domain.policies.uncertainty import UncertaintyPolicy

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
        verbatim_requested: bool = False,
        uncertainty_disposition: UncertaintyDisposition | ResolvedUncertaintyDisposition | None = None,
        uncertainty_reason: str | None = None,
    ) -> CriticGateDecision:
        """Return whether Critic must call an LLM (fail-closed on risk signals)."""
        # Untrusted evidence always fails closed — even for extract asks.
        if contains_untrusted_tool_output(worker_summary):
            return _invoke("untrusted_tool_evidence")

        # §4: raw ``unknown`` at Critic is a leak (forged packet / downstream), not Intent
        # resolve. Never coerce here into ``unknown_fallback:*`` — that wildcard would
        # turn any planted unknown into a free passthrough. Intent must attach
        # ``honest_refusal`` + justified reason before this gate.
        if uncertainty_disposition == "unknown":
            return _invoke("unresolved_unknown_disposition")

        if uncertainty_disposition == "honest_refusal":
            if UncertaintyPolicy.is_justified_refusal_reason(uncertainty_reason):
                return _passthrough("honest_refusal_policy_success")
            return _invoke("unjustified_honest_refusal")

        # Verbatim extract: worker body *is* the answer. Do not invent incompleteness
        # / quality HITL that would also block Formatter passthrough (055).
        if cls._verbatim_passthrough(
            verbatim_requested=verbatim_requested,
            worker_summary=worker_summary,
            worker_confidence=worker_confidence,
            confidence_threshold=confidence_threshold,
        ):
            return _passthrough("verbatim_extraction_passthrough")

        # Singular thread-file re-read (``direct_tool_call`` + sealed body): the tool
        # already ran; judging it as side_effect_risk made Critic revise and Formatter
        # LLM rewrite ALPHA into «файл не приложен» (W10 att_partial).
        if cls._sealed_direct_tool_passthrough(
            selected_strategy=selected_strategy,
            worker_summary=worker_summary,
            worker_confidence=worker_confidence,
            confidence_threshold=confidence_threshold,
        ):
            return _passthrough("sealed_direct_tool_passthrough")

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
            worker_confidence=worker_confidence,
            requires_mcp=requires_mcp,
            requires_tool_call=requires_tool_call,
            has_attachment_context=has_attachment_context,
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
    def _verbatim_passthrough(
        *,
        verbatim_requested: bool,
        worker_summary: str | None,
        worker_confidence: float | None,
        confidence_threshold: float,
    ) -> bool:
        return (
            verbatim_requested
            and bool((worker_summary or "").strip())
            and worker_confidence is not None
            and worker_confidence >= confidence_threshold
        )

    @staticmethod
    def _sealed_direct_tool_passthrough(
        *,
        selected_strategy: ExecutionStrategy,
        worker_summary: str | None,
        worker_confidence: float | None,
        confidence_threshold: float,
    ) -> bool:
        return (
            selected_strategy == "direct_tool_call"
            and bool((worker_summary or "").strip())
            and worker_confidence is not None
            and worker_confidence >= confidence_threshold
        )

    @staticmethod
    def _hard_risk_gate(
        *,
        requires_mcp: bool,
        requires_tool_call: bool,
        worker_summary: str | None,
        has_attachment_context: bool,
    ) -> CriticGateDecision | None:
        _ = worker_summary  # scanned earlier in decide()
        if requires_tool_call or requires_mcp:
            return _invoke("side_effect_risk")
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
        worker_confidence: float | None,
        requires_mcp: bool,
        requires_tool_call: bool,
        has_attachment_context: bool,
    ) -> CriticGateDecision | None:
        # True reformatting of prior content — not bare social synthesis.
        if continuation_kind == "format" or task_kind == "response_formatting":
            if worker_summary and worker_summary.strip():
                return _passthrough("format_passthrough")
            return _invoke("format_without_source")

        # Answer follow-ups usually need the judge (history-blind clarify risk).
        # Green path: high-confidence worker on a low-risk strategy with no side
        # effects / attachments / untrusted fences — deterministic Continuity already
        # remapped the turn, so LLM-as-judge adds cost without new signal.
        if continuation_kind == "answer":
            if (
                selected_strategy in _HIGH_CONFIDENCE_STRATEGIES
                and worker_confidence is not None
                and worker_confidence >= confidence_threshold
                and not requires_mcp
                and not requires_tool_call
                and not has_attachment_context
                and not contains_untrusted_tool_output(worker_summary)
            ):
                return _passthrough("answer_high_confidence_passthrough")
            return _invoke("answer_continuity_gate")

        # Phatic social (no worker, not an answer follow-up): passthrough.
        # Social with a draft, or answer-continuity above, still judges.
        if task_kind == "social_conversation" and selected_strategy == "format_only" and not (worker_summary or "").strip():
            return _passthrough("social_phatic_passthrough")

        # Clarify while user already sent a substantive payload → likely wrong route.
        clarifying = selected_strategy == "clarify" or task_kind == "clarification_needed"
        if clarifying and user_input_chars >= SUBSTANTIVE_USER_PAYLOAD_CHARS:
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
