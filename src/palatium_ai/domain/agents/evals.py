# src/palatium_ai/domain/agents/evals.py

"""Shared eval contract (075) — GradeResult + task helpers."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

# CI baseline comparison tolerance (075); not workflow magic number.
EVAL_BASELINE_TOLERANCE = 0.05


class GradeResult(BaseModel, frozen=True):
    """Outcome of a single eval task grade."""

    score: float = Field(ge=0.0, le=1.0)
    passed: bool
    details: str = Field(min_length=1, max_length=2000)


class EvalTask(BaseModel, frozen=True):
    """Validated task row from tasks.json."""

    id: str
    pass_threshold: float = Field(default=1.0, ge=0.0, le=1.0)
    expect: dict[str, Any] = Field(default_factory=dict)
    fixture_output: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvalTask:
        task_id = raw.get("id") or raw.get("task_id")
        if not isinstance(task_id, str) or not task_id.strip():
            msg = "eval task requires id or task_id"
            raise ValueError(msg)
        threshold = raw.get("pass_threshold", 1.0)
        expect = raw.get("expect", {})
        fixture = raw.get("fixture_output", {})
        if not isinstance(expect, dict) or not isinstance(fixture, dict):
            msg = "expect and fixture_output must be objects"
            raise ValueError(msg)
        return cls(
            id=task_id.strip(),
            pass_threshold=float(threshold),
            expect=expect,
            fixture_output=fixture,
        )


@runtime_checkable
class Grader(Protocol):
    """Eval grader protocol (075)."""

    kind: str

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult: ...


def passed(score: float, *, details: str = "ok") -> GradeResult:
    return GradeResult(score=score, passed=True, details=details)


def failed(score: float, *, details: str) -> GradeResult:
    return GradeResult(score=score, passed=False, details=details)


def resolve_output(task: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    """Prefer runtime output; fall back to fixture_output for deterministic CI."""
    if output:
        return output
    fixture = task.get("fixture_output")
    return fixture if isinstance(fixture, dict) else {}


def matches_expect(expect: dict[str, Any], output: dict[str, Any]) -> tuple[bool, str]:
    for key, expected in expect.items():
        actual = output.get(key)
        if actual != expected:
            return False, f"{key}: expected {expected!r}, got {actual!r}"
    return True, "expectations met"
