# src/palatium_ai/domain/policies/judge.py

"""How four judge scores become one verdict, and who is allowed to judge (W4, 055).

The scoring part is deliberately small and deterministic: the LLM produces four
numbers, and *this* object decides what they mean. Keeping that decision here means a
rubric change and a gate change are separate reviews, and the gate is unit-testable
without a provider.

Two rules shape the verdict:

* **Only two axes are gates.** 040 names accuracy (< 6/10) and safety/grounding
  (< 8/10) as review triggers; that is ``correctness`` and ``groundedness``. Gating
  ``completeness``/``tone`` on an invented threshold would turn a stylistic opinion
  into a workflow block, so they are measured and reported, not enforced.
* **A missing measurement is not a pass.** If a judge call failed, the axis is absent;
  an absent axis must produce ``requires_review``. Treating "we could not measure" as
  "fine" is the Silent-failure antipattern (050), and it is exactly how a broken judge
  would look healthy.

Routing is separate: an answer carrying PII may not be shipped to an external judge
to be scored (020, 060). The policy answers where the call may go — it does not make
the call, so the PII rule is testable without a network.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Literal

from palatium_ai.domain.agents.evals import (
    JUDGE_DIMENSIONS,
    DecomposedVerdict,
    DimensionScore,
    JudgeDimension,
)

#: Axes that can block a turn, with the floors from 040 (`accuracy < 6/10`,
#: `safety < 8/10`). ``completeness``/``tone`` are measured, not gated — see module doc.
GATED_FLOORS: Final[dict[JudgeDimension, float]] = {
    "correctness": 0.6,
    "groundedness": 0.8,
}

#: Spread above which the axes disagree so much that the prompt/model should be looked
#: at. A review signal, not a gate: disagreement describes the answer, not the process.
MAX_DIVERGENCE: Final[float] = 0.3

JudgeRoute = Literal["external_judge", "internal_judge", "requires_review"]


class JudgePolicy:
    """Pure aggregation + routing for the decomposed judge."""

    @classmethod
    def evaluate(cls, scores: Sequence[DimensionScore]) -> DecomposedVerdict:
        """Fold per-axis scores into the verdict; missing axes force review."""
        by_dimension: dict[JudgeDimension, float] = {}
        for score in scores:
            if score.dimension in by_dimension:
                msg = f"duplicate judge dimension: {score.dimension}"
                raise ValueError(msg)
            by_dimension[score.dimension] = score.score

        missing = tuple(dimension for dimension in JUDGE_DIMENSIONS if dimension not in by_dimension)
        below_floor = tuple(
            dimension
            for dimension, floor in GATED_FLOORS.items()
            if dimension in by_dimension and by_dimension[dimension] < floor
        )
        values = list(by_dimension.values())
        overall = sum(values) / len(values) if values else 0.0
        divergence = bool(values) and (max(values) - min(values)) > MAX_DIVERGENCE
        requires_review = bool(missing) or bool(below_floor)
        return DecomposedVerdict(
            scores=tuple(scores),
            overall=overall,
            passed=not requires_review,
            requires_review=requires_review,
            missing=missing,
            below_floor=below_floor,
            divergence=divergence,
        )

    @classmethod
    def route(cls, *, contains_pii: bool, internal_judge_available: bool) -> JudgeRoute:
        """Where the answer may be scored.

        PII never leaves the perimeter for scoring: without an internal judge there is
        no legitimate call at all, and the answer goes to review unscored rather than
        being silently sent outside (020).
        """
        if not contains_pii:
            return "external_judge"
        return "internal_judge" if internal_judge_available else "requires_review"


__all__ = ["GATED_FLOORS", "MAX_DIVERGENCE", "JudgePolicy", "JudgeRoute"]
