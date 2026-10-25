# src/palatium_ai/application/agents/evals/decomposed_judge.py

"""Decomposed LLM judge: four independent calls, one per axis (W4, 040).

Why not one call that returns ``{"score": 0.78}``? Because the number cannot be acted
on. "Correct but incomplete" and "complete but ungrounded" both land around 0.7 and
require different fixes — a better prompt versus better retrieval. Asking one model to
weigh four concerns in one answer also lets a strong impression of two axes hide a
failing third, which is the failure mode 040's unconditional gate exists to catch.

So the axes are measured separately (``correctness``, ``completeness``,
``groundedness``, ``tone``), each by its own rubric, and folded by
``domain.policies.judge.JudgePolicy``. The policy — not this module — decides what the
numbers mean, and a failed call leaves an axis unmeasured, which is a review signal,
never a pass (050: Silent failure).

PII (020/060): an answer flagged ``contains_pii`` is never sent to an external judge
for scoring; without an internal judge the answer goes to review unscored.
"""

from __future__ import annotations

import inspect
import json

from collections.abc import Callable
from typing import Any, Final

from palatium_ai.application.agents.evals.cassette import load_cassette_response
from palatium_ai.application.agents.evals.judge_client import (
    EvalJudgeClientFactory,
    assert_provider_independence,
    create_eval_judge_llm,
    resolve_internal_judge_provider,
    resolve_judge_model,
    resolve_judge_provider,
)
from palatium_ai.application.agents.evals.judge_prompts import (
    DECOMPOSED_JUDGE_SYSTEM_PROMPT,
    DIMENSION_RUBRICS,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.evals import (
    JUDGE_DIMENSIONS,
    DecomposedVerdict,
    DimensionScore,
    GradeResult,
    JudgeDimension,
    failed,
    passed,
)
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage
from palatium_ai.domain.policies.judge import JudgePolicy

logger = get_logger(__name__)

#: Grades one axis: ``(dimension, output)`` → ``DimensionScore`` (sync or awaitable).
#: The rubric is chosen here from the closed set, so a caller cannot score an axis
#: against a different rubric than the one the prompt documents.
DimensionJudgeFn = Callable[[str, dict[str, Any]], Any]

_MAX_REASON_CHARS: Final[int] = 400


def verdict_to_grade(verdict: DecomposedVerdict, *, threshold: float) -> GradeResult:
    """Express the verdict in the eval-report contract without losing the axes."""
    details = [
        " ".join(f"{item.dimension}={item.score:.2f}" for item in verdict.scores),
        f"overall={verdict.overall:.2f}",
    ]
    if verdict.missing:
        details.append(f"missing={','.join(verdict.missing)}")
    if verdict.below_floor:
        details.append(f"below_floor={','.join(verdict.below_floor)}")
    if verdict.divergence:
        details.append("divergence=true")
    text = "; ".join(part for part in details if part)[:_MAX_REASON_CHARS] or "no dimension scored"
    ok = verdict.passed and verdict.overall >= threshold
    return passed(verdict.overall, details=text) if ok else failed(verdict.overall, details=text)


def parse_dimension_payload(raw: str, *, dimension: str) -> DimensionScore | None:
    """Parse one axis response; anything unusable is ``None`` (an unmeasured axis)."""
    try:
        payload = loads_llm_json(raw)
    except json.JSONDecodeError, ValueError:
        logger.warning("judge.decomposed.invalid_json", dimension=dimension)
        return None
    if not isinstance(payload, dict):
        logger.warning("judge.decomposed.invalid_payload", dimension=dimension)
        return None
    raw_score = payload.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        logger.warning("judge.decomposed.invalid_score", dimension=dimension)
        return None
    score = min(max(float(raw_score), 0.0), 1.0)
    reason = str(payload.get("reason") or "")[:_MAX_REASON_CHARS]
    return DimensionScore(dimension=_as_dimension(dimension), score=score, reason=reason)


def _as_dimension(dimension: str) -> JudgeDimension:
    if dimension not in JUDGE_DIMENSIONS:  # pragma: no cover - guarded by caller
        msg = f"unknown judge dimension: {dimension}"
        raise ValueError(msg)
    # Runtime-guarded above; mypy narrows ``str`` through the closed-set membership
    # check on a tuple of Literals, so no cast is needed.
    return dimension


class DecomposedJudgeGrader:
    """Nightly/staging judge: four calls, four metrics, one policy-derived verdict."""

    kind = "decomposed_judge"

    def __init__(
        self,
        *,
        llm_factory: EvalJudgeClientFactory | None = None,
        judge_fn: DimensionJudgeFn | None = None,
    ) -> None:
        self._llm_factory = llm_factory
        self._judge_fn = judge_fn

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult:
        if not output:
            return failed(0.0, details="missing agent output for judge")
        threshold = float(task.get("pass_threshold", 0.7))
        route = JudgePolicy.route(
            contains_pii=_contains_pii(task, output),
            internal_judge_available=resolve_internal_judge_provider() is not None,
        )
        if route == "requires_review":
            # Scoring outside the perimeter is not an option, and an unscored pass
            # would be a fabricated verdict (020).
            return failed(0.0, details="PII output requires review: no internal judge configured")

        try:
            judge = self._judge_fn or self._live_judge(task, external=route == "external_judge")
        except ValueError as exc:
            # Misconfiguration must read as a concrete reason in the report, not as
            # "no judge available" (075: a failing gate has to say what is missing).
            return failed(0.0, details=str(exc))
        if judge is None:
            return failed(0.0, details="decomposed judge requires a judge LLM or an injected judge_fn")

        scores: list[DimensionScore] = []
        for dimension in JUDGE_DIMENSIONS:
            score = await self._score_axis(judge, dimension, output)
            if score is None:
                agent_metrics.record_judge_failed(dimension=dimension)
                continue
            agent_metrics.record_judge_score(dimension=dimension, score=score.score)
            scores.append(score)

        verdict = JudgePolicy.evaluate(scores)
        if verdict.divergence:
            logger.info(
                "judge.decomposed.divergence",
                spread=round(max(item.score for item in verdict.scores) - min(item.score for item in verdict.scores), 3),
                dimensions=[item.dimension for item in verdict.scores],
            )
        return verdict_to_grade(verdict, threshold=threshold)

    async def _score_axis(
        self,
        judge: DimensionJudgeFn,
        dimension: str,
        output: dict[str, Any],
    ) -> DimensionScore | None:
        try:
            result = judge(dimension, output)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001 — a failed axis is a review signal, not a crash (075)
            logger.warning("judge.decomposed.call_failed", dimension=dimension, error=str(exc)[:300])
            return None
        return result if isinstance(result, DimensionScore) else None

    def _live_judge(
        self,
        task: dict[str, Any],
        *,
        external: bool,
    ) -> DimensionJudgeFn | None:
        """Build the per-axis caller: cassette replay first, live LLM only when asked."""
        cassette = task.get("judge_cassette")
        if isinstance(cassette, str) and cassette.strip():
            return _cassette_judge(cassette.strip())
        if self._llm_factory is None:
            return None
        provider = resolve_judge_provider() if external else resolve_internal_judge_provider()
        if provider is None:
            return None
        if external:
            generator_provider = task.get("generator_provider")
            # Independence is a 040 requirement, not a preference: a judge that shares
            # the generator's provider is not an independent measurement.
            assert_provider_independence(
                judge_provider=provider,
                generator_provider=generator_provider if isinstance(generator_provider, str) else None,
            )
        llm = create_eval_judge_llm(self._llm_factory, provider=provider)
        model = resolve_judge_model()

        async def _call(dimension: str, output: dict[str, Any]) -> DimensionScore | None:
            rubric = DIMENSION_RUBRICS[dimension]
            task_rubric = task.get("rubric")
            if isinstance(task_rubric, str) and task_rubric.strip():
                # The axis rubric stays first: task expectations add context, they do
                # not replace the definition of the axis being scored.
                rubric = f"{rubric}\n\nTask-specific expectations: {task_rubric.strip()}"
            messages = [
                ChatMessage(role="system", content=DECOMPOSED_JUDGE_SYSTEM_PROMPT),
                ChatMessage(
                    role="user",
                    content=json.dumps(
                        {"dimension": dimension, "rubric": rubric, "agent_output": output},
                        ensure_ascii=False,
                    ),
                ),
            ]
            completion = await llm.generate(
                messages,
                model=model,
                temperature=0.0,
                response_format="json_object",
            )
            return parse_dimension_payload(completion.content, dimension=dimension)

        return _call


def _cassette_judge(relative_path: str) -> DimensionJudgeFn:
    """Replay recorded per-axis verdicts; a cassette missing an axis measures only what it has.

    A missing axis becomes ``missing`` in the verdict → ``requires_review``. That is
    deliberate: a cassette is a fixture, and silently treating an unrecorded axis as
    passing would let the fixture certify what was never checked.
    """
    raw = load_cassette_response(relative_path)
    try:
        payload = loads_llm_json(raw)
    except json.JSONDecodeError, ValueError:
        payload = None
    scores: dict[str, DimensionScore] = {}
    if isinstance(payload, dict):
        dimensions = payload.get("dimensions")
        if isinstance(dimensions, dict):
            for dimension, value in dimensions.items():
                if dimension in JUDGE_DIMENSIONS and isinstance(value, dict):
                    score = value.get("score")
                    if isinstance(score, (int, float)) and not isinstance(score, bool):
                        scores[dimension] = DimensionScore(
                            dimension=_as_dimension(dimension),
                            score=min(max(float(score), 0.0), 1.0),
                            reason=str(value.get("reason") or "")[:_MAX_REASON_CHARS],
                        )

    def _recall(dimension: str, _output: dict[str, Any]) -> DimensionScore | None:
        return scores.get(dimension)

    return _recall


def _contains_pii(task: dict[str, Any], output: dict[str, Any]) -> bool:
    return bool(task.get("contains_pii") is True or output.get("contains_pii") is True)


decomposed_judge = DecomposedJudgeGrader()

__all__ = [
    "DecomposedJudgeGrader",
    "DimensionJudgeFn",
    "decomposed_judge",
    "parse_dimension_payload",
    "verdict_to_grade",
]
