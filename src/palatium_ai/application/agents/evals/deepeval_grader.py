# src/palatium_ai/application/agents/evals/deepeval_grader.py

"""Optional deepeval metric backend for evals (Phase 6, 075/040).

DeepEval is an *optional* dependency (``pyproject`` group ``eval``): it pulls
gRPC and pytest plugins that must not shape the default PR environment. The
import therefore happens lazily inside the default runner, and the grader
depends on an injected ``MetricRunner`` so the contract is testable without the
package installed. A missing package yields a typed ``passed=False`` result,
never an ``ImportError`` out of the grading path (035 fail-closed on the border).
"""

from __future__ import annotations

import asyncio
import json

from collections.abc import Awaitable, Callable
from importlib.util import find_spec
from typing import Any, Literal

from pydantic import BaseModel, Field

from palatium_ai.application.agents.evals.report import AgentEvalReport, TaskEvalReport
from palatium_ai.application.agents.evals.runner import load_agent_tasks, resolve_task_output
from palatium_ai.domain.agents.evals import GradeResult, failed, passed

#: Task key that opts a case into the metric backend (075 — explicit per case).
DEEPEVAL_TASK_KEY = "deepeval"
#: Default metric threshold when neither task nor spec provides one.
DEEPEVAL_DEFAULT_THRESHOLD = 0.7

DeepEvalMetric = Literal["answer_relevancy", "faithfulness", "g_eval"]
DEEPEVAL_METRICS: tuple[DeepEvalMetric, ...] = ("answer_relevancy", "faithfulness", "g_eval")


class DeepEvalConfigError(ValueError):
    """The task's ``deepeval`` block is malformed or incomplete."""


class DeepEvalSpec(BaseModel, frozen=True):
    """Validated per-task metric request."""

    metric: DeepEvalMetric
    threshold: float = Field(default=DEEPEVAL_DEFAULT_THRESHOLD, ge=0.0, le=1.0)
    criteria: str = ""

    @property
    def resolved_criteria(self) -> str:
        if self.metric == "g_eval":
            if not self.criteria.strip():
                msg = "deepeval g_eval requires non-empty criteria"
                raise DeepEvalConfigError(msg)
            return self.criteria.strip()
        return self.criteria


MetricRunner = Callable[[DeepEvalSpec, dict[str, Any], dict[str, Any]], Awaitable[tuple[float, str]]]


def parse_deepeval_spec(task: dict[str, Any]) -> DeepEvalSpec:
    """Validate and normalize the ``deepeval`` block of one eval case."""
    raw = task.get(DEEPEVAL_TASK_KEY)
    if not isinstance(raw, dict):
        msg = "deepeval task block must be an object"
        raise DeepEvalConfigError(msg)
    metric = raw.get("metric")
    if metric not in DEEPEVAL_METRICS:
        msg = f"unsupported deepeval metric: {metric!r} (expected one of {', '.join(DEEPEVAL_METRICS)})"
        raise DeepEvalConfigError(msg)
    threshold = raw.get("threshold", task.get("pass_threshold", DEEPEVAL_DEFAULT_THRESHOLD))
    criteria = raw.get("criteria", "")
    if not isinstance(criteria, str):
        msg = "deepeval criteria must be a string"
        raise DeepEvalConfigError(msg)
    spec = DeepEvalSpec(metric=metric, threshold=float(threshold), criteria=criteria)
    if spec.metric == "g_eval" and not spec.criteria.strip():
        msg = "deepeval g_eval requires non-empty criteria"
        raise DeepEvalConfigError(msg)
    if spec.metric == "faithfulness" and not isinstance(task.get("retrieval_context"), list):
        msg = "deepeval faithfulness requires a retrieval_context list in the task"
        raise DeepEvalConfigError(msg)
    return spec


def deepeval_installed() -> bool:
    """True when the optional ``deepeval`` dependency is importable."""
    return find_spec("deepeval") is not None


def _json_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


_OUTPUT_TEXT_KEYS: tuple[str, ...] = ("answer", "text", "summary", "output_text", "final_text")


def output_text(output: dict[str, Any]) -> str:
    """Best-effort answer text of an agent output for judging."""
    for key in _OUTPUT_TEXT_KEYS:
        value = output.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return _json_text(output)


def _build_deepeval_metric(spec: DeepEvalSpec) -> Any:
    from deepeval.metrics import AnswerRelevancyMetric, FaithfulnessMetric, GEval
    from deepeval.test_case import LLMTestCaseParams

    if spec.metric == "answer_relevancy":
        return AnswerRelevancyMetric(threshold=spec.threshold, include_reason=True)
    if spec.metric == "faithfulness":
        return FaithfulnessMetric(threshold=spec.threshold, include_reason=True)
    return GEval(
        name="prompt_gate_g_eval",
        criteria=spec.resolved_criteria,
        evaluation_params=[LLMTestCaseParams.INPUT, LLMTestCaseParams.ACTUAL_OUTPUT],
        threshold=spec.threshold,
    )


def _build_deepeval_case(task: dict[str, Any], output: dict[str, Any]) -> Any:
    from deepeval.test_case import LLMTestCase

    expected = task.get("expected_output")
    retrieval = task.get("retrieval_context")
    return LLMTestCase(
        input=_json_text(task.get("input", "")),
        actual_output=output_text(output),
        expected_output=expected if isinstance(expected, str) else None,
        retrieval_context=[str(item) for item in retrieval] if isinstance(retrieval, list) else None,
    )


async def run_deepeval_metric(spec: DeepEvalSpec, task: dict[str, Any], output: dict[str, Any]) -> tuple[float, str]:
    """Default runner: measure one deepeval metric (blocking SDK → thread)."""
    metric = _build_deepeval_metric(spec)
    case = _build_deepeval_case(task, output)
    measure = getattr(metric, "a_measure", None)
    if measure is None:
        await asyncio.to_thread(metric.measure, case)
    else:
        await measure(case)
    score = getattr(metric, "score", None)
    reason = getattr(metric, "reason", "")
    return float(score if score is not None else 0.0), str(reason or "")


class DeepEvalGrader:
    """Grade a case with a deepeval metric; injectable runner for tests/CI."""

    kind = "deepeval"

    def __init__(self, *, runner: MetricRunner | None = None) -> None:
        self._runner: MetricRunner | None = runner

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult:
        if not output:
            return failed(0.0, details="missing agent output for deepeval metric")
        try:
            spec = parse_deepeval_spec(task)
        except ValueError as exc:  # DeepEvalConfigError + bad numeric fields
            return failed(0.0, details=f"invalid deepeval spec: {exc}")

        runner = self._runner or run_deepeval_metric
        if self._runner is None and not deepeval_installed():
            return failed(
                0.0,
                details="deepeval backend unavailable: install the eval dependency group (uv sync --group eval)",
            )

        try:
            score, reason = await runner(spec, task, output)
        except Exception as exc:  # noqa: BLE001  # third-party SDK: eval degrades to a scored failure (035)
            return failed(0.0, details=f"deepeval metric failed: {exc}")

        bounded = min(max(float(score), 0.0), 1.0)
        details = f"{spec.metric}: {reason.strip() or 'no reason'}"
        threshold = float(task.get("pass_threshold", spec.threshold))
        return passed(bounded, details=details) if bounded >= threshold else failed(bounded, details=details)


async def run_deepeval_evals(agent: str, *, grader: DeepEvalGrader | None = None) -> AgentEvalReport:
    """Grade every case of ``agent`` that opts into the deepeval backend."""
    tasks = [raw for raw in load_agent_tasks(agent) if DEEPEVAL_TASK_KEY in raw]
    active = grader or DeepEvalGrader()
    task_reports: list[TaskEvalReport] = []
    for raw_task in tasks:
        task_id = str(raw_task.get("id") or raw_task.get("task_id") or "deepeval-task")
        output, mode = await resolve_task_output(agent, raw_task)
        grade = await active.grade(raw_task, output)
        threshold = float(raw_task.get("pass_threshold", DEEPEVAL_DEFAULT_THRESHOLD))
        task_reports.append(
            TaskEvalReport(
                task_id=task_id,
                score=grade.score,
                passed=grade.passed and grade.score >= threshold,
                details=grade.details,
                mode=f"deepeval:{mode}",
            )
        )
    total = len(task_reports)
    passed_count = sum(1 for item in task_reports if item.passed)
    return AgentEvalReport(
        agent=agent,
        score=passed_count / total if total else 1.0,
        passed=passed_count,
        total=total,
        tasks=tuple(task_reports),
        details=tuple(f"{item.task_id}: {item.details}" for item in task_reports if not item.passed),
    )
