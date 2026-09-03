# src/palatium_ai/application/agents/critic/evals/grader.py

"""Deterministic grader for Critic harness and policy gate eval tasks."""

from __future__ import annotations

from typing import Any

from palatium_ai.domain.agents.evals import GradeResult, failed, passed, resolve_output
from palatium_ai.domain.policies import CriticPolicy


def _grade_resolved(expect: dict[str, Any], resolved: dict[str, Any]) -> GradeResult:
    for key, expected in expect.items():
        if key.endswith("_min"):
            field = key[:-4]
            actual = resolved.get(field)
            if not isinstance(actual, (int, float)) or actual < expected:
                return failed(0.0, details=f"{field}: {actual!r} < min {expected!r}")
            continue
        actual = resolved.get(key)
        if actual != expected:
            return failed(0.0, details=f"{key}: expected {expected!r}, got {actual!r}")
    return passed(1.0, details="critic harness ok")


class CriticGrader:
    kind = "deterministic"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult:
        expect = task.get("expect")
        if not isinstance(expect, dict):
            return failed(0.0, details="invalid expect")

        resolved = resolve_output(task, output)
        if resolved:
            return _grade_resolved(expect, resolved)

        raw_input = task.get("input")
        if not isinstance(raw_input, dict):
            return failed(0.0, details="invalid input")

        decision = CriticPolicy.decide(
            selected_strategy=raw_input["selected_strategy"],
            task_kind=raw_input["task_kind"],
            continuation_kind=raw_input.get("continuation_kind"),
            classification_confidence=float(raw_input["classification_confidence"]),
            confidence_threshold=float(raw_input["confidence_threshold"]),
            requires_mcp=bool(raw_input["requires_mcp"]),
            requires_tool_call=bool(raw_input["requires_tool_call"]),
            worker_summary=raw_input.get("worker_summary"),
            user_input_chars=int(raw_input.get("user_input_chars", 0)),
        )
        policy_output = {
            "invoke_llm": decision.invoke_llm,
            "reason": decision.reason,
        }
        return _grade_resolved(expect, policy_output)


grader = CriticGrader()
