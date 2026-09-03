# tests/eval/test_agent_eval_assets.py

"""Validate per-agent eval assets and baseline gate (075)."""

from __future__ import annotations

import importlib
import json

from pathlib import Path

import pytest

from palatium_ai.application.agents.evals import run_all_agent_evals
from palatium_ai.application.agents.evals.llm_judge import grade_from_judge_payload, llm_judge
from palatium_ai.application.agents.evals.runner import (
    assert_baseline_gate,
    assert_nightly_baseline_gate,
    build_suite_report,
    load_baseline,
    load_nightly_baseline,
    load_nightly_tasks,
    run_all_nightly_evals,
)
from palatium_ai.domain.agents.evals import Grader

_AGENTS_ROOT = Path(__file__).resolve().parents[2] / "src" / "palatium_ai" / "application" / "agents"

_AGENT_EVAL_PACKAGES: tuple[str, ...] = (
    "intent_classifier",
    "context_enricher",
    "supervisor",
    "researcher",
    "memory_keeper",
    "critic",
    "formatter",
    "text_ingestor",
)


def _agent_eval_dir(agent: str) -> Path:
    return _AGENTS_ROOT / agent / "evals"


@pytest.mark.parametrize("agent", _AGENT_EVAL_PACKAGES)
def test_agent_has_eval_assets(agent: str) -> None:
    eval_dir = _agent_eval_dir(agent)
    assert (eval_dir / "tasks.json").is_file(), f"missing tasks.json for {agent}"
    assert (eval_dir / "grader.py").is_file(), f"missing grader.py for {agent}"


@pytest.mark.parametrize("agent", _AGENT_EVAL_PACKAGES)
def test_agent_grader_implements_protocol(agent: str) -> None:
    module = importlib.import_module(f"palatium_ai.application.agents.{agent}.evals.grader")
    grader = getattr(module, "grader", None)
    assert isinstance(grader, Grader), f"{agent} must export protocol grader"
    assert grader.kind == "deterministic"


@pytest.mark.parametrize("agent", _AGENT_EVAL_PACKAGES)
def test_agent_tasks_json_loads(agent: str) -> None:
    tasks_path = _agent_eval_dir(agent) / "tasks.json"
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    assert isinstance(tasks, list)
    assert tasks, f"empty tasks.json for {agent}"
    for task in tasks:
        assert isinstance(task, dict)
        assert task.get("id") or task.get("task_id"), f"task missing id in {agent}"


def test_baseline_covers_all_agents() -> None:
    agent_baseline, _ = load_baseline()
    for agent in _AGENT_EVAL_PACKAGES:
        assert agent in agent_baseline, f"missing baseline for {agent}"


@pytest.mark.asyncio
async def test_all_agent_evals_pass_baseline_gate() -> None:
    reports = await run_all_agent_evals()
    for agent, report in reports.items():
        assert report.passed == report.total, f"{agent} failures: {report.details}"
    assert_baseline_gate(reports)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("agent", "task_id"),
    [
        ("intent_classifier", "knowledge_with_mcp"),
        ("intent_classifier", "social_phatic"),
        ("context_enricher", "continuation-format-followup"),
        ("context_enricher", "continuation-answer-followup"),
        ("context_enricher", "continuation-new-topic"),
        ("researcher", "researcher-knowledge"),
        ("researcher", "researcher-search-knowledge"),
        ("researcher", "researcher-search-memory"),
        ("researcher", "researcher-graph-query"),
        ("researcher", "researcher-web-fallback"),
        ("memory_keeper", "keeper-preference"),
        ("supervisor", "social-formatter"),
        ("critic", "format_passthrough_with_source"),
        ("formatter", "minimal_document"),
        ("text_ingestor", "paragraph-split"),
        ("text_ingestor", "context-prefix-enrich"),
    ],
)
async def test_cassette_task_runs_through_harness(agent: str, task_id: str) -> None:
    reports = await run_all_agent_evals()
    cassette_task = next(item for item in reports[agent].tasks if item.task_id == task_id)
    assert cassette_task.mode == "cassette"
    assert cassette_task.passed is True


def test_suite_report_serializes() -> None:
    from palatium_ai.application.agents.evals.report import AgentEvalReport

    reports = {"critic": AgentEvalReport(agent="critic", score=1.0, passed=1, total=1)}
    payload = build_suite_report(reports).to_json()
    assert '"schema_version": 1' in payload


def test_nightly_tasks_load() -> None:
    tasks = load_nightly_tasks()
    assert tasks, "nightly_tasks.json should define at least one task"
    for task in tasks:
        assert task.get("id")
        assert task.get("agent")
        assert task.get("judge_cassette")


@pytest.mark.asyncio
async def test_nightly_llm_judge_passes_with_cassette() -> None:
    reports = await run_all_nightly_evals()
    nightly = reports["nightly"]
    assert nightly.passed == nightly.total
    assert_nightly_baseline_gate(reports)
    for task in load_nightly_tasks():
        item = next(row for row in nightly.tasks if row.task_id == task["id"])
        assert item.passed is True
        assert item.mode.startswith("llm_judge:")


def test_nightly_baseline_covers_tasks() -> None:
    _, task_baseline = load_nightly_baseline()
    for task in load_nightly_tasks():
        key = f"nightly/{task['id']}"
        assert key in task_baseline, f"missing nightly baseline for {key}"


def test_grade_from_judge_payload_threshold() -> None:
    ok = grade_from_judge_payload({"score": 0.85, "passed": True, "details": "ok"}, threshold=0.7)
    assert ok.passed is True
    low = grade_from_judge_payload({"score": 0.5, "details": "weak"}, threshold=0.7)
    assert low.passed is False


@pytest.mark.asyncio
async def test_live_judge_rejects_same_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PALATIUM_EVAL_LIVE_JUDGE", "1")
    monkeypatch.setenv("PALATIUM_EVAL_JUDGE_PROVIDER", "openai")
    result = await llm_judge.grade(
        {
            "rubric": "test",
            "generator_provider": "openai",
            "pass_threshold": 0.7,
        },
        {"summary": "sample"},
    )
    assert result.passed is False
    assert "differ" in result.details
