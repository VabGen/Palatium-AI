"""Executable collapse for task kinds the graph cannot yet decompose."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from palatium_ai.domain.agents.intent import TaskKind


class WorkflowExecutionPolicy:
    """Until Planner emits N steps + graph can loop workers, multi_step is one pass.

    Keeps Intent's ``multi_step_workflow`` label for metrics, but routing/plan use an
    executable kind so we never claim a multi-step plan the platform cannot run.
    """

    @classmethod
    def executable_task_kind(
        cls,
        task_kind: TaskKind,
        *,
        requires_mcp: bool,
    ) -> TaskKind:
        """Map declared kind → kind the Supervisor/Planner can actually execute."""
        if task_kind != "multi_step_workflow":
            return task_kind
        return "tool_execution" if requires_mcp else "knowledge_request"

    @classmethod
    def plan_for(
        cls,
        task_kind: TaskKind,
        *,
        requires_mcp: bool,
        default_plans: dict[TaskKind, str],
    ) -> str:
        """Honest plan text (no false multi-step claims)."""
        if task_kind == "multi_step_workflow":
            executable = cls.executable_task_kind(task_kind, requires_mcp=requires_mcp)
            base = default_plans.get(executable) or default_plans["clarification_needed"]
            return (
                f"multi_step_workflow is not decomposable yet; collapse to single worker pass as {executable}. {base}"
            )
        plan = default_plans.get(task_kind)
        if plan is None:
            return default_plans["clarification_needed"]
        return plan
