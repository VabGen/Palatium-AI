# src/palatium_ai/application/agents/evals/llm_judge.py

"""LLM-as-judge eval for nightly runs (075) — not used on PR CI."""

from __future__ import annotations

import json
import os

from typing import Any

from palatium_ai.application.agents.evals.cassette import load_cassette_response
from palatium_ai.application.agents.evals.judge_client import (
    assert_provider_independence,
    create_eval_judge_llm,
    resolve_judge_model,
    resolve_judge_provider,
)
from palatium_ai.application.agents.evals.judge_prompts import JUDGE_SYSTEM_PROMPT
from palatium_ai.domain.agents.evals import GradeResult, failed, passed
from palatium_ai.domain.llm.json_codec import loads_llm_json
from palatium_ai.domain.llm.models import ChatMessage


def grade_from_judge_payload(payload: dict[str, Any], *, threshold: float) -> GradeResult:
    score = float(payload.get("score", 0.0))
    score = min(max(score, 0.0), 1.0)
    judge_passed = payload.get("passed")
    ok = judge_passed if isinstance(judge_passed, bool) else score >= threshold
    details = str(payload.get("details", "llm_judge ok"))
    return passed(score, details=details) if ok else failed(score, details=details)


class LlmJudgeGrader:
    kind = "llm_judge"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult:
        if not output:
            return failed(0.0, details="missing agent output for judge")

        threshold = float(task.get("pass_threshold", 0.7))

        if os.environ.get("PALATIUM_EVAL_LIVE_JUDGE") == "1":
            return await self._grade_live(task, output, threshold=threshold)

        judge_cassette = task.get("judge_cassette")
        if not isinstance(judge_cassette, str) or not judge_cassette.strip():
            return failed(0.0, details="missing judge_cassette for nightly eval")

        raw = load_cassette_response(judge_cassette.strip())
        try:
            payload = loads_llm_json(raw)
        except json.JSONDecodeError, ValueError:
            return failed(0.0, details="judge cassette must be JSON object")

        if not isinstance(payload, dict):
            return failed(0.0, details="judge cassette must be JSON object")

        return grade_from_judge_payload(payload, threshold=threshold)

    async def _grade_live(
        self,
        task: dict[str, Any],
        output: dict[str, Any],
        *,
        threshold: float,
    ) -> GradeResult:
        rubric = task.get("rubric")
        if not isinstance(rubric, str) or not rubric.strip():
            return failed(0.0, details="missing rubric for live judge")

        try:
            judge_provider = resolve_judge_provider()
            generator_provider = task.get("generator_provider")
            if not isinstance(generator_provider, str):
                generator_provider = os.environ.get("PALATIUM_EVAL_AGENT_PROVIDER")
            assert_provider_independence(
                judge_provider=judge_provider,
                generator_provider=generator_provider if isinstance(generator_provider, str) else None,
            )
            llm = create_eval_judge_llm()
        except ValueError as exc:
            return failed(0.0, details=str(exc))

        messages = [
            ChatMessage(role="system", content=JUDGE_SYSTEM_PROMPT),
            ChatMessage(
                role="user",
                content=json.dumps(
                    {"rubric": rubric.strip(), "agent_output": output},
                    ensure_ascii=False,
                ),
            ),
        ]

        try:
            completion = await llm.generate(
                messages,
                model=resolve_judge_model(),
                temperature=0.0,
                response_format="json_object",
            )
            payload = loads_llm_json(completion.content)
        except Exception as exc:
            return failed(0.0, details=f"live judge LLM failed: {exc}")

        if not isinstance(payload, dict):
            return failed(0.0, details="live judge response must be JSON object")

        return grade_from_judge_payload(payload, threshold=threshold)


llm_judge = LlmJudgeGrader()
