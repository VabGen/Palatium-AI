# src/palatium_ai/application/agents/coder/evals/grader.py

"""Deterministic grader for coder cassette tasks."""

from __future__ import annotations

from typing import Any


def grade(task: dict[str, Any], output: dict[str, Any]) -> dict[str, Any]:
    expect = task.get("expect") or {}
    ok = True
    reasons: list[str] = []
    if expect.get("status") and output.get("status") != expect["status"]:
        ok = False
        reasons.append(f"status={output.get('status')}")
    summary = str(output.get("summary") or "")
    min_chars = int(expect.get("summary_min_chars") or 0)
    if len(summary.strip()) < min_chars:
        ok = False
        reasons.append("summary_too_short")
    return {"pass": ok, "reasons": reasons}
