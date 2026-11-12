"""Deterministic grader for analyst cassette tasks (075 Protocol)."""

from __future__ import annotations

from typing import Any

from palatium_ai.domain.agents.evals import GradeResult, failed, matches_expect, passed, resolve_output


class AnalystGrader:
    kind = "deterministic"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> GradeResult:
        expect = task.get("expect")
        if not isinstance(expect, dict):
            return failed(0.0, details="invalid expect")
        resolved = resolve_output(task, output)
        summary = str(resolved.get("summary") or "")
        min_chars = int(expect.get("summary_min_chars") or 0)
        if min_chars and len(summary.strip()) < min_chars:
            return failed(0.0, details="summary_too_short")
        min_findings = int(expect.get("min_findings") or 0)
        findings = resolved.get("findings")
        if min_findings and (not isinstance(findings, list) or len(findings) < min_findings):
            return failed(0.0, details="findings_too_few")
        field_expect = {k: v for k, v in expect.items() if k not in {"summary_min_chars", "min_findings"}}
        if not field_expect:
            return passed(1.0, details="summary_ok")
        ok, msg = matches_expect(field_expect, resolved)
        return passed(1.0, details=msg) if ok else failed(0.0, details=msg)


grader = AnalystGrader()
