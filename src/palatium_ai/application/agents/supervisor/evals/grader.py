# src/palatium_ai/application/agents/supervisor/evals/grader.py

"""Deterministic grader for Supervisor routing eval tasks."""

from __future__ import annotations

from typing import Any

from palatium_ai.application.agents.supervisor.routing import ROUTE_MATRIX
from palatium_ai.domain.agents.evals import failed, matches_expect, passed, resolve_output


class SupervisorGrader:
    kind = "deterministic"

    async def grade(self, task: dict[str, Any], output: dict[str, Any]) -> Any:
        expect = task.get("expect")
        if isinstance(expect, dict):
            resolved = resolve_output(task, output)
            if resolved:
                ok, msg = matches_expect(expect, resolved)
                return passed(1.0, details=msg) if ok else failed(0.0, details=msg)

        expected_route = task.get("expected_route")
        task_kind = task.get("task_kind")
        if not isinstance(expected_route, str) or not isinstance(task_kind, str):
            return failed(0.0, details="missing expect or expected_route/task_kind")
        route, _ = ROUTE_MATRIX.get(task_kind, ("researcher", "researcher"))
        if route == expected_route:
            return passed(1.0, details=f"route={route} for {task_kind}")
        return failed(0.0, details=f"expected {expected_route}, matrix gives {route}")


grader = SupervisorGrader()
