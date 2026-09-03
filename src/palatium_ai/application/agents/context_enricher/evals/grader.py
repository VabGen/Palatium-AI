# src/palatium_ai/application/agents/context_enricher/evals/grader.py

"""Deterministic grader for context_enricher continuation eval tasks."""

from __future__ import annotations

from typing import Any

from palatium_ai.domain.agents.evals import failed, matches_expect, passed, resolve_output


class ContextEnricherGrader:
    kind = "deterministic"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> Any:
        expect = task.get("expect")
        if not isinstance(expect, dict):
            return failed(0.0, details="invalid expect")
        resolved = resolve_output(task, output)
        ok, msg = matches_expect(expect, resolved)
        return passed(1.0, details=msg) if ok else failed(0.0, details=msg)


grader = ContextEnricherGrader()
