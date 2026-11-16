"""Decomposed judge (W4): four axes, one policy verdict, no invented pass.

The policy is what these tests are really about — it is where an unmeasured axis or a
violated 040 floor has to turn into ``requires_review`` instead of a passing score. The
grader tests only prove the wiring: one call per axis, one metric per call, and PII
never leaving the perimeter.
"""

from __future__ import annotations

import json

from typing import cast

import pytest

from palatium_ai.application.agents.evals.decomposed_judge import (
    DecomposedJudgeGrader,
    parse_dimension_payload,
    verdict_to_grade,
)
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.evals import JUDGE_DIMENSIONS, DimensionScore, JudgeDimension
from palatium_ai.domain.policies.judge import MAX_DIVERGENCE, JudgePolicy

OUTPUT = {"status": "success", "summary": "Готово."}


def _score(dimension: str, value: float, *, reason: str = "") -> DimensionScore:
    return DimensionScore(dimension=cast("JudgeDimension", dimension), score=value, reason=reason)


def _scores(**overrides: float) -> list[DimensionScore]:
    values = {"correctness": 0.9, "completeness": 0.85, "groundedness": 0.9, "tone": 0.8}
    values.update(overrides)
    return [_score(dimension, score) for dimension, score in values.items()]


# --- policy -----------------------------------------------------------------


def test_all_axes_above_floor_pass() -> None:
    verdict = JudgePolicy.evaluate(_scores())

    assert verdict.passed is True
    assert verdict.requires_review is False
    assert verdict.missing == ()
    assert verdict.below_floor == ()
    assert verdict.overall == pytest.approx(0.8625)


def test_missing_axis_is_review_not_silent_pass() -> None:
    """A failed judge call must not read as "that axis was fine" (050)."""
    verdict = JudgePolicy.evaluate(_scores()[:3])

    assert verdict.passed is False
    assert verdict.requires_review is True
    assert verdict.missing == ("tone",)


def test_accuracy_below_040_floor_requires_review() -> None:
    verdict = JudgePolicy.evaluate(_scores(correctness=0.59))

    assert verdict.requires_review is True
    assert verdict.below_floor == ("correctness",)


def test_groundedness_floor_is_higher_than_accuracy() -> None:
    """040: safety < 8/10 blocks; accuracy < 6/10 blocks. Same score, different verdicts."""
    grounded = JudgePolicy.evaluate(_scores(groundedness=0.75))
    assert grounded.below_floor == ("groundedness",)

    accurate = JudgePolicy.evaluate(_scores(correctness=0.65))
    assert accurate.below_floor == ()


def test_completeness_and_tone_are_measured_not_gated() -> None:
    """Gating a stylistic axis on an invented threshold would block on opinion."""
    verdict = JudgePolicy.evaluate(_scores(completeness=0.2, tone=0.1))

    assert verdict.below_floor == ()
    assert verdict.passed is True
    assert verdict.overall < 0.6


def test_divergence_is_a_signal_not_a_gate() -> None:
    verdict = JudgePolicy.evaluate(_scores(correctness=0.95, tone=0.95, completeness=0.4, groundedness=0.95))

    assert verdict.divergence is True
    assert verdict.requires_review is False


def test_no_divergence_within_the_limit() -> None:
    verdict = JudgePolicy.evaluate(_scores(correctness=0.9, tone=0.9 - MAX_DIVERGENCE))
    assert verdict.divergence is False


def test_duplicate_dimension_is_a_programming_error() -> None:
    with pytest.raises(ValueError, match="duplicate judge dimension"):
        JudgePolicy.evaluate([_score("tone", 0.9), _score("tone", 0.8)])


def test_no_scores_is_review_with_zero_overall() -> None:
    verdict = JudgePolicy.evaluate([])

    assert verdict.requires_review is True
    assert verdict.overall == 0.0
    assert verdict.missing == JUDGE_DIMENSIONS


# --- routing ----------------------------------------------------------------


def test_plain_output_may_go_to_an_external_judge() -> None:
    assert JudgePolicy.route(contains_pii=False, internal_judge_available=False) == "external_judge"


def test_pii_prefers_the_internal_judge() -> None:
    assert JudgePolicy.route(contains_pii=True, internal_judge_available=True) == "internal_judge"


def test_pii_without_internal_judge_goes_to_review_not_outside() -> None:
    assert JudgePolicy.route(contains_pii=True, internal_judge_available=False) == "requires_review"


# --- grader -----------------------------------------------------------------


def test_payload_parsing_rejects_anything_unusable() -> None:
    parsed = parse_dimension_payload('{"score": 0.7, "reason": "ok"}', dimension="tone")
    assert parsed == _score("tone", 0.7, reason="ok")
    assert parse_dimension_payload("not json", dimension="tone") is None
    assert parse_dimension_payload('{"score": true}', dimension="tone") is None
    assert parse_dimension_payload('{"reason": "no score"}', dimension="tone") is None
    clamped = parse_dimension_payload('{"score": 3}', dimension="tone")
    assert clamped is not None
    assert clamped.score == 1.0


@pytest.mark.asyncio()
async def test_grader_calls_each_axis_once_and_records_scores() -> None:
    calls: list[str] = []

    def judge(dimension: str, _output: dict[str, object]) -> DimensionScore:
        calls.append(dimension)
        return _score(dimension, 0.9)

    grader = DecomposedJudgeGrader(judge_fn=judge)
    before = {dimension: agent_metrics.judge_score_count(dimension) for dimension in JUDGE_DIMENSIONS}

    grade = await grader.grade({"pass_threshold": 0.7}, OUTPUT)

    assert calls == list(JUDGE_DIMENSIONS)
    assert grade.passed is True
    assert grade.score == pytest.approx(0.9)
    for dimension in JUDGE_DIMENSIONS:
        assert agent_metrics.judge_score_count(dimension) == before[dimension] + 1


@pytest.mark.asyncio()
async def test_failed_axis_is_counted_and_blocks_the_pass() -> None:
    def judge(dimension: str, _output: dict[str, object]) -> DimensionScore | None:
        if dimension == "groundedness":
            raise RuntimeError("provider timeout")
        return _score(dimension, 0.95)

    grader = DecomposedJudgeGrader(judge_fn=judge)
    before_failed = agent_metrics.judge_failure_count("groundedness")

    grade = await grader.grade({"pass_threshold": 0.7}, OUTPUT)

    assert grade.passed is False
    assert "missing=groundedness" in grade.details
    assert agent_metrics.judge_failure_count("groundedness") == before_failed + 1


@pytest.mark.asyncio()
async def test_async_judge_is_awaited() -> None:
    async def judge(dimension: str, _output: dict[str, object]) -> DimensionScore:
        return _score(dimension, 0.9)

    grade = await DecomposedJudgeGrader(judge_fn=judge).grade({"pass_threshold": 0.7}, OUTPUT)
    assert grade.passed is True


@pytest.mark.asyncio()
async def test_pii_without_internal_judge_is_reviewed_before_any_call() -> None:
    calls: list[str] = []

    def judge(dimension: str, _output: dict[str, object]) -> DimensionScore:
        calls.append(dimension)
        return _score(dimension, 1.0)

    grader = DecomposedJudgeGrader(judge_fn=judge)

    grade = await grader.grade({"contains_pii": True}, OUTPUT)

    assert grade.passed is False
    assert "requires review" in grade.details
    assert calls == [], "no scoring call may happen for PII without an internal judge"


@pytest.mark.asyncio()
async def test_missing_output_is_not_graded() -> None:
    grade = await DecomposedJudgeGrader().grade({}, {})
    assert grade.passed is False
    assert "missing agent output" in grade.details


def test_verdict_to_grade_reports_every_axis() -> None:
    verdict = JudgePolicy.evaluate(_scores(correctness=0.4))
    grade = verdict_to_grade(verdict, threshold=0.7)

    assert grade.passed is False
    assert "correctness=0.40" in grade.details
    assert "below_floor=correctness" in grade.details


def test_prompt_rubrics_cover_exactly_the_closed_axis_set() -> None:
    """A new axis without a rubric would silently fail every call."""
    from palatium_ai.application.agents.evals.judge_prompts import DIMENSION_RUBRICS

    assert set(DIMENSION_RUBRICS) == set(JUDGE_DIMENSIONS)


@pytest.mark.asyncio()
async def test_nightly_runner_opts_in_per_task(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``judge_mode: decomposed`` is per task: older baselines cannot express four axes."""
    from pathlib import Path

    from palatium_ai.application.agents.evals import (
        cassette as cassette_module,
        runner as runner_module,
    )

    root = Path(str(tmp_path))
    (root / "judge").mkdir(parents=True, exist_ok=True)
    (root / "judge" / "decomposed_all.json").write_text(
        json.dumps(
            {
                "response": {
                    "dimensions": {
                        "correctness": {"score": 0.9},
                        "completeness": {"score": 0.9},
                        "groundedness": {"score": 0.9},
                        "tone": {"score": 0.9},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cassette_module, "_CASSETTE_ROOT", root)
    monkeypatch.setattr(
        runner_module,
        "load_nightly_tasks",
        lambda: [
            {
                "id": "decomposed-task",
                "agent": "researcher",
                "judge_mode": "decomposed",
                "judge_cassette": "judge/decomposed_all.json",
                "fixture_output": {"status": "success"},
                "pass_threshold": 0.7,
            }
        ],
    )

    report = await runner_module.run_nightly_evals()

    assert report.passed == 1
    assert report.tasks[0].mode == "decomposed_judge:fixture"


@pytest.mark.asyncio()
async def test_shared_provider_with_the_generator_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """040: a judge on the generator's provider is not an independent measurement."""
    monkeypatch.setenv("PALATIUM_EVAL_JUDGE_PROVIDER", "openai")

    grade = await DecomposedJudgeGrader(llm_factory=lambda _provider: object()).grade(  # type: ignore[arg-type,return-value]
        {"generator_provider": "openai"},
        OUTPUT,
    )

    assert grade.passed is False
    assert "must differ from generator provider" in grade.details


@pytest.mark.asyncio()
async def test_cassette_judge_measures_only_recorded_axes(
    tmp_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrecorded axis stays missing → review; a fixture must not certify it."""
    from pathlib import Path

    from palatium_ai.application.agents.evals import cassette as cassette_module

    root = Path(str(tmp_path))
    (root / "judge").mkdir(parents=True, exist_ok=True)
    (root / "judge" / "decomposed_partial.json").write_text(
        json.dumps(
            {
                "response": {
                    "dimensions": {
                        "correctness": {"score": 0.9},
                        "completeness": {"score": 0.9},
                        "groundedness": {"score": 0.9},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cassette_module, "_CASSETTE_ROOT", root)

    grade = await DecomposedJudgeGrader().grade(
        {"judge_cassette": "judge/decomposed_partial.json", "pass_threshold": 0.7},
        OUTPUT,
    )

    assert grade.passed is False
    assert "missing=tone" in grade.details
