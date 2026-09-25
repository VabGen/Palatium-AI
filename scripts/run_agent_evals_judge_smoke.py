#!/usr/bin/env python
"""Smoke live llm_judge provider (staging ops — not PR CI)."""

from __future__ import annotations

import asyncio
import os
import sys

from palatium_ai.application.agents.evals.llm_judge import LlmJudgeGrader
from palatium_ai.core.config.settings import get_settings
from palatium_ai.domain.ports.llm import LLMPort
from palatium_ai.infrastructure.llm.factory import create_llm_client


def _judge_llm_factory(provider: str) -> LLMPort:
    """Composition root for the eval judge: injects the concrete LLM adapter."""
    return create_llm_client(get_settings(), provider)


judge = LlmJudgeGrader(llm_factory=_judge_llm_factory)

_SMOKE_TASK: dict[str, object] = {
    "rubric": (
        "The agent output should mention a layered platform with orchestration "
        "or guardrails (Harness / LangGraph / MCP)."
    ),
    "pass_threshold": 0.5,
}

_SMOKE_OUTPUT: dict[str, object] = {
    "summary": (
        "Palatium is a layered agent platform with Harness guardrails, LangGraph orchestration, and MCP tools."
    ),
    "status": "success",
}


def _env_check() -> str | None:
    if os.environ.get("PALATIUM_EVAL_LIVE_JUDGE") != "1":
        return "set PALATIUM_EVAL_LIVE_JUDGE=1"
    if not os.environ.get("PALATIUM_EVAL_JUDGE_PROVIDER", "").strip():
        return "set PALATIUM_EVAL_JUDGE_PROVIDER (e.g. anthropic)"
    generator = os.environ.get("PALATIUM_EVAL_AGENT_PROVIDER", "openai").strip().lower()
    judge = os.environ.get("PALATIUM_EVAL_JUDGE_PROVIDER", "").strip().lower()
    if generator and judge == generator:
        return "PALATIUM_EVAL_JUDGE_PROVIDER must differ from PALATIUM_EVAL_AGENT_PROVIDER (040)"
    return None


async def _main() -> int:
    err = _env_check()
    if err:
        print(f"agent_evals_judge_smoke: {err}")
        return 1

    task = {
        **_SMOKE_TASK,
        "generator_provider": os.environ.get("PALATIUM_EVAL_AGENT_PROVIDER", "openai"),
    }
    result = await judge.grade(task, _SMOKE_OUTPUT)
    print(f"score={result.score:.3f} passed={result.passed} details={result.details}")
    if not result.passed:
        print("agent_evals_judge_smoke: FAIL")
        return 1
    print("agent_evals_judge_smoke: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_main()))
