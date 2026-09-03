# tests/eval/test_agent_evals_llm_live.py

"""Live llm_judge evals — opt-in via PALATIUM_EVAL_LIVE_JUDGE=1 (075, not PR CI)."""

from __future__ import annotations

import os

import pytest

from palatium_ai.application.agents.evals.llm_judge import llm_judge
from palatium_ai.application.agents.evals.runner import assert_nightly_baseline_gate, run_all_nightly_evals


def _live_judge_env_ok() -> bool:
    return os.environ.get("PALATIUM_EVAL_LIVE_JUDGE") == "1" and bool(
        os.environ.get("PALATIUM_EVAL_JUDGE_PROVIDER", "").strip()
    )


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_live_judge_smoke_grade() -> None:
    if not _live_judge_env_ok():
        pytest.skip("PALATIUM_EVAL_LIVE_JUDGE and PALATIUM_EVAL_JUDGE_PROVIDER required")

    result = await llm_judge.grade(
        {
            "rubric": (
                "Output mentions a layered platform with orchestration or guardrails (Harness / LangGraph / MCP)."
            ),
            "generator_provider": os.environ.get("PALATIUM_EVAL_AGENT_PROVIDER", "openai"),
            "pass_threshold": 0.5,
        },
        {
            "summary": (
                "Palatium is a layered agent platform with Harness guardrails, LangGraph orchestration, and MCP tools."
            ),
            "status": "success",
        },
    )
    assert result.passed is True
    assert result.score >= 0.5


@pytest.mark.llm_live
@pytest.mark.asyncio
async def test_nightly_suite_with_live_judge() -> None:
    """Full nightly suite with live judge — only when PALATIUM_EVAL_LIVE_NIGHTLY=1."""
    if not _live_judge_env_ok():
        pytest.skip("PALATIUM_EVAL_LIVE_JUDGE and PALATIUM_EVAL_JUDGE_PROVIDER required")
    if os.environ.get("PALATIUM_EVAL_LIVE_NIGHTLY") != "1":
        pytest.skip("set PALATIUM_EVAL_LIVE_NIGHTLY=1 for full live nightly suite")

    reports = await run_all_nightly_evals()
    nightly = reports["nightly"]
    assert nightly.passed == nightly.total, nightly.details
    assert_nightly_baseline_gate(reports)
