# src/palatium_ai/domain/policies/uncertainty.py

"""Stateless uncertainty disposition for incomplete inputs (prompt-audit backlog §4).

Contract (not a prompt phrase): when the turn lacks enough information, choose one
explicit outcome — never invent. Multi-turn anaphora resolution belongs to §5 /
ContinuityPolicy; this policy only sees *signals* (e.g. anaphora without prior).

``unknown`` is a *residual* from ``decide`` — policy could not pick among
clarification / default_with_mark / honest_refusal. It is **not** user-facing
«не знаю». ``proceed`` means evidence is sufficient (incl. prior dialog grounds
the ask) — no assumption mark. Pipeline code must call ``resolve_for_downstream``
(or ``for_pipeline``) before attaching the disposition to Intent → ContextPacket
→ Formatter/Critic.

Composes ClarificationGatePolicy + GroundingPolicy; does not re-implement their rules.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.intent import IntentClassifierOutput
from palatium_ai.domain.content.content_document import VerbosityBudget
from palatium_ai.domain.policies.clarification import CLARIFY_MIN_CONFIDENCE, ClarificationGatePolicy
from palatium_ai.domain.policies.grounding import GroundingPolicy
from palatium_ai.domain.policies.types import (
    GroundingMode,
    ResolvedUncertaintyDisposition,
    TaskKind,
    UncertaintyDisposition,
    UnderspecificationKind,
)

#: Structural assumption marker for ``default_with_mark``. Not subject to
#: ``verbosity_budget`` trimming — honesty > brevity (Formatter contract).
ASSUMPTION_MARK: Final[str] = "Предположение:"

_UNKNOWN_FALLBACK_REASON: Final[str] = "unknown_fallback"

#: Reasons that make ``honest_refusal`` a Critic passthrough (policy success).
#: Bare disposition without one of these is unjustified → Critic must invoke.
_JUSTIFIED_REFUSAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "out_of_scope",
        "required_data_absent",
    }
)


class UncertaintySignals(BaseModel):
    """Pure inputs — no I/O, no phrase lists (055)."""

    model_config = {"frozen": True}

    task_kind: TaskKind
    underspecification_kind: UnderspecificationKind = "none"
    requires_user_choice: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    grounding: GroundingMode = "optional"
    has_prior_dialog: bool = False
    has_attachment_context: bool = False
    #: None = retrieval not run yet; True = ran and empty; False = had hits.
    retrieval_empty: bool | None = None
    #: Capability / safety: ask is outside product scope.
    out_of_scope: bool = False
    #: «как в прошлый раз» / anaphora with no thread evidence (stateless half of §5).
    ambiguous_reference_without_prior: bool = False
    #: Continuity trusts prior / slot filled from dialog — answer is not an assumption.
    prior_grounds_answer: bool = False


class UncertaintyDecision(BaseModel):
    """Chosen disposition + machine-readable reason (for evals / audit)."""

    model_config = {"frozen": True}

    disposition: UncertaintyDisposition
    reason: str = Field(min_length=1, max_length=128)


class UncertaintyPolicy:
    """Pure domain policy: signals → one of four dispositions (no mixing)."""

    @classmethod
    def decide(
        cls,
        signals: UncertaintySignals,
        *,
        min_confidence: float = CLARIFY_MIN_CONFIDENCE,
    ) -> UncertaintyDecision:
        if signals.out_of_scope:
            return UncertaintyDecision(disposition="honest_refusal", reason="out_of_scope")

        if signals.ambiguous_reference_without_prior and not signals.has_prior_dialog:
            return UncertaintyDecision(
                disposition="clarification",
                reason="ambiguous_reference_without_prior",
            )

        if signals.retrieval_empty is True and not signals.prior_grounds_answer:
            mode = GroundingPolicy.coerce_mode(signals.grounding)
            empty = GroundingPolicy.decide_empty_retrieval(enabled=True, grounding=mode)
            if empty.action == "clarify" or mode == "required":
                return UncertaintyDecision(disposition="honest_refusal", reason="required_data_absent")
            if mode == "optional":
                return UncertaintyDecision(disposition="default_with_mark", reason="optional_retrieval_empty")
            return UncertaintyDecision(disposition="default_with_mark", reason="grounding_none_empty")

        if signals.task_kind == "clarification_needed":
            intent = IntentClassifierOutput(
                task_kind="clarification_needed",
                requires_mcp=False,
                requires_user_choice=signals.requires_user_choice,
                underspecification_kind=signals.underspecification_kind,
                confidence=signals.confidence,
                grounding=signals.grounding,
                reasoning="uncertainty_policy",
            )
            if ClarificationGatePolicy.is_justified(intent, min_confidence=min_confidence):
                return UncertaintyDecision(disposition="clarification", reason="named_gap_justified")
            return UncertaintyDecision(
                disposition="default_with_mark",
                reason="clarify_demoted_unjustified",
            )

        # Residual: in-scope ask, confidence below gate — policy cannot honestly pick
        # clarify / marked-default / refuse. Downstream must resolve (not show raw).
        if signals.confidence < min_confidence and signals.task_kind in {
            "knowledge_request",
            "tool_execution",
            "multi_step_workflow",
        }:
            return UncertaintyDecision(disposition="unknown", reason="low_confidence_in_scope")

        # Dialog already supplies the referent (Continuity trust / slot filled) —
        # answering from prior is not an assumption (055: class of false mark).
        if signals.prior_grounds_answer and signals.has_prior_dialog:
            return UncertaintyDecision(disposition="proceed", reason="prior_dialog_grounds")

        return UncertaintyDecision(disposition="proceed", reason="sufficient_to_proceed")

    @classmethod
    def resolve_for_downstream(cls, decision: UncertaintyDecision) -> UncertaintyDecision:
        """Map residual ``unknown`` → ``honest_refusal`` before pipeline attach.

        Downstream (Formatter/Critic) must never see raw ``unknown`` — it is an
        internal residual, not a user-facing «не знаю» outcome. Idempotent: a
        second call on an already-resolved decision is a no-op (no resolve loop).
        """
        if decision.disposition != "unknown":
            return decision
        reason = f"{_UNKNOWN_FALLBACK_REASON}:{decision.reason}"
        return UncertaintyDecision(disposition="honest_refusal", reason=reason[:128])

    @classmethod
    def coerce_for_downstream(
        cls,
        disposition: UncertaintyDisposition | str | None,
        *,
        reason: str | None = None,
    ) -> UncertaintyDecision | None:
        """Pure per-call resolve when a raw ``unknown`` leaks past Intent attach.

        Not a stateful one-shot: each call with ``unknown`` yields a terminal
        ``honest_refusal``. If ``reason`` already carries ``unknown_fallback:``
        (prior coerce did not stick — still presented as unknown), reason becomes
        ``unknown_fallback:exhausted`` so callers can detect a stuck residual.
        Idempotent on already-resolved dispositions. Returns None when absent.
        """
        if disposition is None:
            return None
        if disposition == "unknown":
            base = (reason or "unspecified").strip()
            if base.startswith(f"{_UNKNOWN_FALLBACK_REASON}:"):
                return UncertaintyDecision(
                    disposition="honest_refusal",
                    reason="unknown_fallback:exhausted",
                )
            return cls.resolve_for_downstream(UncertaintyDecision(disposition="unknown", reason=base[:128]))
        if disposition in {"clarification", "default_with_mark", "honest_refusal", "proceed"}:
            return UncertaintyDecision(
                disposition=disposition,  # type: ignore[arg-type]
                reason=(reason or "attached")[:128],
            )
        return None

    @classmethod
    def is_justified_refusal_reason(cls, reason: str | None) -> bool:
        """True when honest_refusal has a policy trigger (not a free-form dodge).

        ``unknown_fallback:*`` counts only when Intent already resolved residual
        unknown into ``honest_refusal`` (attached reason). Critic must not invent
        that prefix by coercing a planted ``unknown`` at the gate.
        """
        if not reason:
            return False
        if reason in _JUSTIFIED_REFUSAL_REASONS:
            return True
        if reason == "unknown_fallback:exhausted":
            return False
        return reason.startswith(f"{_UNKNOWN_FALLBACK_REASON}:")

    @classmethod
    def for_pipeline(
        cls,
        signals: UncertaintySignals,
        *,
        min_confidence: float = CLARIFY_MIN_CONFIDENCE,
    ) -> UncertaintyDecision:
        """Decide + resolve — only entry for Intent → Formatter → Critic."""
        return cls.resolve_for_downstream(cls.decide(signals, min_confidence=min_confidence))

    @classmethod
    def resolved_disposition(cls, decision: UncertaintyDecision) -> ResolvedUncertaintyDisposition:
        """Typed resolved disposition for contract fields (never ``unknown``)."""
        resolved = cls.resolve_for_downstream(decision)
        disposition = resolved.disposition
        if disposition == "unknown":  # pragma: no cover - resolve always maps unknown
            msg = "resolve_for_downstream left unknown"
            raise RuntimeError(msg)
        return disposition

    @classmethod
    def requires_assumption_mark(cls, disposition: UncertaintyDisposition | None) -> bool:
        return disposition == "default_with_mark"

    @classmethod
    def stream_prefix(cls, disposition: UncertaintyDisposition | None) -> str | None:
        """Text that must be painted *before* the first LLM stream chunk (or None).

        Ends with a blank line so CommonMark ATHeading markers (``## …``) in the
        following body stay at column 0. Same-line glue
        (``Предположение: ## Title``) leaves ``##`` as literal text in preview
        and collapses the heading when worker GFM is parsed.
        """
        if not cls.requires_assumption_mark(disposition):
            return None
        return f"{ASSUMPTION_MARK}\n\n"

    @classmethod
    def mark_exempt_from_verbosity(
        cls,
        *,
        disposition: UncertaintyDisposition | None,
        verbosity_budget: VerbosityBudget | str | None,
    ) -> bool:
        """Assumption mark is structural — ``minimal`` budget must not strip it."""
        _ = verbosity_budget
        return cls.requires_assumption_mark(disposition)

    @classmethod
    def assumption_mark_preserved(
        cls,
        body: str,
        *,
        disposition: UncertaintyDisposition | None,
        mark: str = ASSUMPTION_MARK,
    ) -> bool:
        """True when mark is present if required; True when mark not required."""
        if not cls.requires_assumption_mark(disposition):
            return True
        return mark in body

    @classmethod
    def with_disposition(
        cls,
        intent: IntentClassifierOutput,
        signals: UncertaintySignals,
        *,
        min_confidence: float = CLARIFY_MIN_CONFIDENCE,
    ) -> IntentClassifierOutput:
        """Attach resolved disposition + reason to Intent (post-LLM; never raw ``unknown``)."""
        decision = cls.for_pipeline(signals, min_confidence=min_confidence)
        return intent.model_copy(
            update={
                "uncertainty_disposition": cls.resolved_disposition(decision),
                "uncertainty_reason": decision.reason,
            },
        )

    @classmethod
    def ensure_assumption_mark(
        cls,
        body: str,
        *,
        disposition: UncertaintyDisposition | None,
        mark: str = ASSUMPTION_MARK,
    ) -> str:
        """Prepend structural mark when required and missing (verbosity-safe).

        Mark is its own paragraph (blank line after). Inline glue would break
        ATHeading / list / fence constructs that must start at column 0.
        """
        text = body.strip()
        if not text or not cls.requires_assumption_mark(disposition):
            return body
        if mark in text:
            return body
        return f"{mark}\n\n{text}"
