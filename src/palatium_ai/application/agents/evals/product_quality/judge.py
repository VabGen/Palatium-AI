# src/palatium_ai/application/agents/evals/product_quality/judge.py

"""Optional W9 LLM-judge — only after rule gate passes (verifier's law)."""

from __future__ import annotations

import json
import os

from typing import Any

from palatium_ai.application.agents.evals.judge_client import (
    EvalJudgeClientFactory,
    assert_provider_independence,
    create_eval_judge_llm,
    resolve_judge_provider,
)
from palatium_ai.application.agents.evals.product_quality.case_schema import ProductQualityCase
from palatium_ai.application.agents.evals.product_quality.w9_judge_prompts import (
    ANAPHORA_RESOLUTION_RUBRIC,
    EXPLANATION_CORRECTNESS_RUBRIC,
    JUDGE_PROMPT_VERSION,
    W9_JUDGE_SYSTEM,
)
from palatium_ai.domain.agents.evals import GradeResult, failed, passed
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage


def _rubric_for(case: ProductQualityCase) -> str:
    if case.suite == "multi_turn":
        return ANAPHORA_RESOLUTION_RUBRIC
    return EXPLANATION_CORRECTNESS_RUBRIC


async def grade_with_judge(
    case: ProductQualityCase,
    answer: str,
    *,
    llm_factory: EvalJudgeClientFactory | None = None,
) -> GradeResult:
    """Live judge only when ``PALATIUM_EVAL_LIVE_JUDGE=1``; otherwise skip-pass after rules."""
    if os.environ.get("PALATIUM_EVAL_LIVE_JUDGE") != "1":
        return passed(
            1.0,
            details=f"judge skipped (cassette/PR); prompt_version={JUDGE_PROMPT_VERSION}",
        )
    if llm_factory is None:
        return failed(0.0, details="live judge requires llm_factory")

    judge_provider = resolve_judge_provider()
    generator_provider = os.environ.get("PALATIUM_EVAL_AGENT_PROVIDER")
    assert_provider_independence(
        judge_provider=judge_provider,
        generator_provider=generator_provider,
    )
    llm = create_eval_judge_llm(llm_factory, provider=judge_provider)
    payload_obj: dict[str, Any] = {
        "case_id": case.id,
        "scenario": case.scenario,
        "expected": case.expected,
        "context": case.context,
        "answer": answer,
        "rubric": _rubric_for(case),
        "judge_prompt_version": JUDGE_PROMPT_VERSION,
    }
    messages = (
        ChatMessage(role="system", content=W9_JUDGE_SYSTEM),
        ChatMessage(role="user", content=json.dumps(payload_obj, ensure_ascii=False)),
    )
    raw = await llm.chat(messages)
    try:
        payload = loads_llm_json(raw if isinstance(raw, str) else str(raw))
    except json.JSONDecodeError, ValueError, TypeError:
        return failed(0.0, details="judge returned non-JSON")
    if not isinstance(payload, dict):
        return failed(0.0, details="judge payload must be object")
    score_raw = payload.get("score", 0)
    try:
        score_int = int(score_raw)
    except TypeError, ValueError:
        return failed(0.0, details="judge score not int")
    ok = bool(payload.get("passed")) if "passed" in payload else score_int >= 2
    details = str(payload.get("details") or f"judge score={score_int}")
    # Map 0/1/2 → 0.0/0.5/1.0 for GradeResult.
    norm = {0: 0.0, 1: 0.5, 2: 1.0}.get(score_int, 0.0)
    return passed(norm, details=details) if ok and score_int >= 2 else failed(norm, details=details)


__all__ = ["grade_with_judge"]
