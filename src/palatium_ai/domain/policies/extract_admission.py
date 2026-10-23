# src/palatium_ai/domain/policies/extract_admission.py

"""Admission for the implicit per-turn memory **extract** (060, 080).

Every finished turn used to enqueue a sleep-time extract job, and each job is one
MemoryKeeper LLM call over the last dialog window (~12k chars + up to 20 known
facts). Firing it on "спасибо" prices a frontier-tier call for a turn that carries
nothing a later turn could recall.

Admission is decided from the turn's own axes — ``task_kind`` and the selected
strategy — never from phrase lists or a length heuristic (055): a *short* question
can carry a durable preference, while a *long* social turn carries none. Length is
not the signal; what the turn answered is.

Pure policy: no I/O, no config reads, deterministic.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import TaskKind

# Turns that answer nothing worth recalling:
#   social_conversation — phatic exchange; the *content* turn it reacts to was admitted;
#   clarification_needed — the assistant asked back, so the turn holds no fact at all.
_NON_RECALLABLE_TASK_KINDS: frozenset[str] = frozenset({"social_conversation", "clarification_needed"})

# Strategies whose answer is presentation of material the dialog already holds, or a
# question with no answer yet. The producing turn was admitted on its own route, so
# re-extracting from the restatement would duplicate that memory at full LLM cost.
_NON_RECALLABLE_STRATEGIES: frozenset[str] = frozenset({"ack_only", "format_only", "clarify"})


class ExtractAdmissionDecision(BaseModel):
    """Outcome of ``ExtractAdmissionPolicy`` for one finished turn."""

    model_config = {"frozen": True}

    admit: bool
    reason: str = Field(min_length=1, max_length=64)


class ExtractAdmissionPolicy:
    """Pure domain policy: does this turn belong in medium-term memory?"""

    @classmethod
    def decide(
        cls,
        *,
        task_kind: TaskKind | str | None,
        strategy: str | None,
    ) -> ExtractAdmissionDecision:
        """Skip recall-empty turns; admit everything substantive.

        Unknown/missing axes admit: refusing on absent evidence would silently stop
        learning from turns the caller simply did not classify (fail-open on purpose).
        """
        kind = (task_kind or "").strip()
        if kind in _NON_RECALLABLE_TASK_KINDS:
            return ExtractAdmissionDecision(admit=False, reason=f"task_kind:{kind}")
        route = (strategy or "").strip()
        if route in _NON_RECALLABLE_STRATEGIES:
            return ExtractAdmissionDecision(admit=False, reason=f"strategy:{route}")
        return ExtractAdmissionDecision(admit=True, reason="admitted")


__all__ = ["ExtractAdmissionDecision", "ExtractAdmissionPolicy"]
