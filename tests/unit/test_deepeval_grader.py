# tests/unit/test_deepeval_grader.py

"""deepeval adapter contract — testable without the optional package (Phase 6, 075)."""

from __future__ import annotations

import pytest

from palatium_ai.application.agents.evals import deepeval_grader
from palatium_ai.application.agents.evals.deepeval_grader import (
    DeepEvalConfigError,
    DeepEvalGrader,
    DeepEvalSpec,
    output_text,
    parse_deepeval_spec,
    run_deepeval_evals,
)

_TASK = {
    "id": "metric-case",
    "pass_threshold": 0.8,
    "input": {"user_text": "дай в виде таблицы"},
    "deepeval": {"metric": "answer_relevancy", "threshold": 0.7},
}
_OUTPUT = {"answer": "| a | b |"}


def test_parse_spec_defaults_threshold_from_task() -> None:
    spec = parse_deepeval_spec({"deepeval": {"metric": "answer_relevancy"}, "pass_threshold": 0.65})
    assert spec.metric == "answer_relevancy"
    assert spec.threshold == pytest.approx(0.65)


def test_parse_spec_rejects_unknown_metric() -> None:
    with pytest.raises(DeepEvalConfigError, match="unsupported deepeval metric"):
        parse_deepeval_spec({"deepeval": {"metric": "bleu"}})


def test_parse_spec_requires_g_eval_criteria() -> None:
    with pytest.raises(DeepEvalConfigError, match="requires non-empty criteria"):
        parse_deepeval_spec({"deepeval": {"metric": "g_eval"}})


def test_parse_spec_requires_retrieval_context_for_faithfulness() -> None:
    with pytest.raises(DeepEvalConfigError, match="retrieval_context"):
        parse_deepeval_spec({"deepeval": {"metric": "faithfulness"}})


def test_parse_spec_accepts_faithfulness_with_context() -> None:
    spec = parse_deepeval_spec({"deepeval": {"metric": "faithfulness"}, "retrieval_context": ["doc"]})
    assert spec.metric == "faithfulness"


def test_output_text_prefers_answer_keys() -> None:
    assert output_text({"answer": "text", "output_text": "other"}) == "text"
    assert output_text({"output_text": "fallback"}) == "fallback"
    assert output_text({"nested": {"a": 1}}).startswith("{")


@pytest.mark.asyncio()
async def test_grade_passes_with_injected_runner() -> None:
    async def runner(spec: DeepEvalSpec, task: dict[str, object], output: dict[str, object]) -> tuple[float, str]:
        assert spec.metric == "answer_relevancy"
        return 0.9, "relevant"

    grade = await DeepEvalGrader(runner=runner).grade(_TASK, _OUTPUT)
    assert grade.passed is True
    assert grade.score == pytest.approx(0.9)
    assert "answer_relevancy" in grade.details


@pytest.mark.asyncio()
async def test_grade_fails_below_pass_threshold() -> None:
    async def runner(spec: DeepEvalSpec, task: dict[str, object], output: dict[str, object]) -> tuple[float, str]:
        return 0.5, "weak"

    grade = await DeepEvalGrader(runner=runner).grade(_TASK, _OUTPUT)
    assert grade.passed is False
    assert grade.score == pytest.approx(0.5)


@pytest.mark.asyncio()
async def test_grade_clamps_out_of_range_scores() -> None:
    async def runner(spec: DeepEvalSpec, task: dict[str, object], output: dict[str, object]) -> tuple[float, str]:
        return 1.7, "overflow"

    grade = await DeepEvalGrader(runner=runner).grade(_TASK, _OUTPUT)
    assert grade.score == pytest.approx(1.0)


@pytest.mark.asyncio()
async def test_grade_without_backend_is_typed_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(deepeval_grader, "deepeval_installed", lambda: False)
    grade = await DeepEvalGrader().grade(_TASK, _OUTPUT)
    assert grade.passed is False
    assert grade.score == pytest.approx(0.0)
    assert "backend unavailable" in grade.details


@pytest.mark.asyncio()
async def test_grade_runner_exception_degrades_to_failure() -> None:
    async def runner(spec: DeepEvalSpec, task: dict[str, object], output: dict[str, object]) -> tuple[float, str]:
        msg = "provider timeout"
        raise RuntimeError(msg)

    grade = await DeepEvalGrader(runner=runner).grade(_TASK, _OUTPUT)
    assert grade.passed is False
    assert "metric failed" in grade.details


@pytest.mark.asyncio()
async def test_grade_missing_output_fails() -> None:
    grade = await DeepEvalGrader(runner=None).grade(_TASK, {})
    assert grade.passed is False
    assert "missing agent output" in grade.details


@pytest.mark.asyncio()
async def test_grade_invalid_spec_fails_without_raising() -> None:
    grade = await DeepEvalGrader().grade({"id": "bad", "deepeval": {"metric": "bleu"}}, _OUTPUT)
    assert grade.passed is False
    assert "invalid deepeval spec" in grade.details


@pytest.mark.asyncio()
async def test_run_deepeval_evals_grades_opted_in_cases_only() -> None:
    async def runner(spec: DeepEvalSpec, task: dict[str, object], output: dict[str, object]) -> tuple[float, str]:
        return 0.95, "ok"

    report = await run_deepeval_evals("critic", grader=DeepEvalGrader(runner=runner))
    assert report.total >= 1
    assert report.passed == report.total
    assert all(task.mode.startswith("deepeval:") for task in report.tasks)
