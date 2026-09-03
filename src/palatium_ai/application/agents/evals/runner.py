# src/palatium_ai/application/agents/evals/runner.py

"""Load tasks.json, grade via Grader protocol, compare to baseline (075)."""

from __future__ import annotations

import importlib
import json

from pathlib import Path
from typing import Any

from palatium_ai.application.agents.evals.cassette import run_cassette_task
from palatium_ai.application.agents.evals.llm_judge import llm_judge
from palatium_ai.application.agents.evals.report import AgentEvalReport, EvalSuiteReport, TaskEvalReport
from palatium_ai.domain.agents.evals import (
    EVAL_BASELINE_TOLERANCE,
    EvalTask,
    Grader,
)

_AGENTS_ROOT = Path(__file__).resolve().parent.parent
_BASELINE_PATH = Path(__file__).resolve().parent / "baseline.json"
_NIGHTLY_BASELINE_PATH = Path(__file__).resolve().parent / "nightly_baseline.json"
_NIGHTLY_TASKS_PATH = Path(__file__).resolve().parent / "nightly_tasks.json"

_AGENT_PACKAGES: tuple[str, ...] = (
    "intent_classifier",
    "context_enricher",
    "supervisor",
    "researcher",
    "memory_keeper",
    "critic",
    "formatter",
    "text_ingestor",
)


def _load_grader(agent: str) -> Grader:
    module = importlib.import_module(f"palatium_ai.application.agents.{agent}.evals.grader")
    grader = getattr(module, "grader", None)
    if grader is None or not isinstance(grader, Grader):
        msg = f"{agent}.evals.grader must export `grader` implementing Grader protocol"
        raise TypeError(msg)
    if grader.kind != "deterministic":
        msg = f"{agent} grader kind must be deterministic for PR CI"
        raise ValueError(msg)
    return grader


def _load_tasks(agent: str) -> list[dict[str, Any]]:
    path = _AGENTS_ROOT / agent / "evals" / "tasks.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list) or not raw:
        msg = f"tasks.json for {agent} must be a non-empty list"
        raise ValueError(msg)
    return [item for item in raw if isinstance(item, dict)]


def load_baseline() -> tuple[dict[str, float], dict[str, float]]:
    payload = json.loads(_BASELINE_PATH.read_text(encoding="utf-8"))
    agents = payload.get("agents", {})
    tasks = payload.get("tasks", {})
    if not isinstance(agents, dict):
        msg = "baseline.json agents must be an object"
        raise ValueError(msg)
    if not isinstance(tasks, dict):
        msg = "baseline.json tasks must be an object"
        raise ValueError(msg)
    return (
        {str(name): float(score) for name, score in agents.items()},
        {str(name): float(score) for name, score in tasks.items()},
    )


def load_nightly_baseline() -> tuple[dict[str, float], dict[str, float]]:
    payload = json.loads(_NIGHTLY_BASELINE_PATH.read_text(encoding="utf-8"))
    agents = payload.get("agents", {})
    tasks = payload.get("tasks", {})
    if not isinstance(agents, dict):
        msg = "nightly_baseline.json agents must be an object"
        raise ValueError(msg)
    if not isinstance(tasks, dict):
        msg = "nightly_baseline.json tasks must be an object"
        raise ValueError(msg)
    return (
        {str(name): float(score) for name, score in agents.items()},
        {str(name): float(score) for name, score in tasks.items()},
    )


async def _resolve_task_output(
    agent: str,
    raw_task: dict[str, Any],
    runtime_output: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    if runtime_output:
        return runtime_output, "runtime"
    cassette = raw_task.get("cassette")
    args_cassette = raw_task.get("args_cassette")
    if (isinstance(cassette, str) and cassette.strip()) or (isinstance(args_cassette, str) and args_cassette.strip()):
        return await run_cassette_task(agent, raw_task), "cassette"
    if raw_task.get("fixture_output"):
        fixture = raw_task.get("fixture_output")
        return fixture if isinstance(fixture, dict) else {}, "fixture"
    return {}, "fixture"


async def run_agent_evals(agent: str, *, output: dict[str, Any] | None = None) -> AgentEvalReport:
    grader = _load_grader(agent)
    tasks = _load_tasks(agent)
    runtime_output = output or {}
    task_reports: list[TaskEvalReport] = []
    for raw_task in tasks:
        task = EvalTask.from_dict(raw_task)
        merged = {**raw_task, "id": task.id, "expect": task.expect, "fixture_output": task.fixture_output}
        task_output, mode = await _resolve_task_output(agent, raw_task, runtime_output)
        grade = await grader.grade(merged, task_output)
        passed_task = grade.passed and grade.score >= task.pass_threshold
        final = grade if passed_task else grade.model_copy(update={"passed": False})
        task_reports.append(
            TaskEvalReport(
                task_id=task.id,
                score=final.score,
                passed=final.passed,
                details=final.details,
                mode=mode,
            )
        )
    total = len(task_reports)
    passed_count = sum(1 for item in task_reports if item.passed)
    score = passed_count / total if total else 0.0
    return AgentEvalReport(
        agent=agent,
        score=score,
        passed=passed_count,
        total=total,
        tasks=tuple(task_reports),
        details=tuple(f"{item.task_id}: {item.details}" for item in task_reports if not item.passed),
    )


async def run_all_agent_evals() -> dict[str, AgentEvalReport]:
    reports: dict[str, AgentEvalReport] = {}
    for agent in _AGENT_PACKAGES:
        reports[agent] = await run_agent_evals(agent)
    return reports


def load_nightly_tasks() -> list[dict[str, Any]]:
    if not _NIGHTLY_TASKS_PATH.is_file():
        return []
    payload = json.loads(_NIGHTLY_TASKS_PATH.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        tasks = payload.get("tasks", [])
        if isinstance(tasks, list):
            return [item for item in tasks if isinstance(item, dict)]
    msg = 'nightly_tasks.json must be a list or {"tasks": [...]}'
    raise ValueError(msg)


async def run_nightly_evals() -> AgentEvalReport:
    tasks = load_nightly_tasks()
    task_reports: list[TaskEvalReport] = []
    for raw_task in tasks:
        task_id = str(raw_task.get("id") or raw_task.get("task_id") or "nightly-task")
        agent = raw_task.get("agent")
        if not isinstance(agent, str) or not agent.strip():
            task_reports.append(
                TaskEvalReport(
                    task_id=task_id,
                    score=0.0,
                    passed=False,
                    details="missing agent",
                    mode="llm_judge",
                )
            )
            continue
        agent_output, mode = await _resolve_task_output(agent.strip(), raw_task, {})
        merged = {**raw_task, "id": task_id}
        grade = await llm_judge.grade(merged, agent_output)
        threshold = float(raw_task.get("pass_threshold", 0.7))
        passed_task = grade.passed and grade.score >= threshold
        final = grade if passed_task else grade.model_copy(update={"passed": False})
        task_reports.append(
            TaskEvalReport(
                task_id=task_id,
                score=final.score,
                passed=final.passed,
                details=final.details,
                mode=f"llm_judge:{mode}",
            )
        )
    total = len(task_reports)
    passed_count = sum(1 for item in task_reports if item.passed)
    score = passed_count / total if total else 1.0
    return AgentEvalReport(
        agent="nightly",
        score=score,
        passed=passed_count,
        total=total,
        tasks=tuple(task_reports),
        details=tuple(f"{item.task_id}: {item.details}" for item in task_reports if not item.passed),
    )


async def run_all_nightly_evals() -> dict[str, AgentEvalReport]:
    tasks = load_nightly_tasks()
    if not tasks:
        return {}
    return {"nightly": await run_nightly_evals()}


def build_suite_report(reports: dict[str, AgentEvalReport]) -> EvalSuiteReport:
    return EvalSuiteReport.from_reports(reports, tolerance=EVAL_BASELINE_TOLERANCE)


def assert_baseline_gate(
    reports: dict[str, AgentEvalReport],
    *,
    tolerance: float = EVAL_BASELINE_TOLERANCE,
) -> None:
    agent_baseline, task_baseline = load_baseline()
    failures: list[str] = []
    for agent, report in reports.items():
        expected = agent_baseline.get(agent)
        if expected is None:
            failures.append(f"{agent}: missing agent baseline score")
            continue
        floor = expected - tolerance
        if report.score < floor:
            failures.append(f"{agent}: score {report.score:.3f} < baseline {expected:.3f} - tolerance {tolerance:.3f}")
        for task in report.tasks:
            key = f"{agent}/{task.task_id}"
            task_expected = task_baseline.get(key)
            if task_expected is None:
                continue
            task_floor = task_expected - tolerance
            if task.score < task_floor:
                failures.append(
                    f"{key}: score {task.score:.3f} < baseline {task_expected:.3f} - tolerance {tolerance:.3f}"
                )
    if failures:
        raise AssertionError("; ".join(failures))


def assert_nightly_baseline_gate(
    reports: dict[str, AgentEvalReport],
    *,
    tolerance: float = EVAL_BASELINE_TOLERANCE,
) -> None:
    agent_baseline, task_baseline = load_nightly_baseline()
    failures: list[str] = []
    for agent, report in reports.items():
        expected = agent_baseline.get(agent)
        if expected is None:
            failures.append(f"{agent}: missing nightly agent baseline score")
            continue
        floor = expected - tolerance
        if report.score < floor:
            failures.append(
                f"{agent}: score {report.score:.3f} < nightly baseline {expected:.3f} - tolerance {tolerance:.3f}"
            )
        for task in report.tasks:
            key = f"{agent}/{task.task_id}"
            task_expected = task_baseline.get(key)
            if task_expected is None:
                continue
            task_floor = task_expected - tolerance
            if task.score < task_floor:
                failures.append(
                    f"{key}: score {task.score:.3f} < nightly baseline {task_expected:.3f} - tolerance {tolerance:.3f}"
                )
    if failures:
        raise AssertionError("; ".join(failures))
