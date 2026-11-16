"""Executable collapse for task kinds the graph cannot yet decompose."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from palatium_ai.domain.agents.intent import TaskKind

#: Kinds the Formatter can satisfy without a tool. A thread file re-read converts these
#: into a research step — the text is in storage, not in the prior answer.
_TOOL_BOUND_KINDS: Final[frozenset[str]] = frozenset({"response_formatting"})


class WorkflowExecutionPolicy:
    """Fail-safe if Intent still emits ``multi_step_workflow`` (reserved in prompt).

    Intent must not select multi_step until the graph can loop N worker steps.
    This policy keeps routing honest: collapse to a single executable kind and
    never claim a multi-step plan the platform cannot run.
    """

    @classmethod
    def executable_task_kind(
        cls,
        task_kind: TaskKind,
        *,
        requires_mcp: bool,
        thread_file_reread: bool = False,
    ) -> TaskKind:
        """Map declared kind → kind the Supervisor/Planner can actually execute.

        ``thread_file_reread``: the ask targets a file this dialog already holds and the
        turn carries no fence of its own, so the body lives in storage and only a tool
        call can produce it. Restyling prior text cannot answer such a turn — routing it
        to the Formatter is precisely how the assistant ended up asking the user to
        "attach the file again" while the file was still in the thread (055).
        """
        if task_kind == "multi_step_workflow":
            return "tool_execution" if requires_mcp else "knowledge_request"
        if task_kind == "social_conversation" and requires_mcp:
            # Phatic Formatter path is only valid while the turn needs no external tool:
            # an MCP-needing ask is a tool request, and routing it to the Formatter would
            # answer without ever calling the tool. Intent may still label it
            # ``social_conversation`` for metrics (055).
            return "tool_execution"
        if thread_file_reread and task_kind in _TOOL_BOUND_KINDS:
            # A storage read is a research step regardless of what the user wants done
            # with the text afterwards (summary, style, comparison).
            return "knowledge_request"
        return task_kind

    @classmethod
    def plan_for(
        cls,
        task_kind: TaskKind,
        *,
        requires_mcp: bool,
        default_plans: dict[TaskKind, str],
    ) -> str:
        """Honest plan text (no false multi-step claims, no plan contradicting the route)."""
        executable = cls.executable_task_kind(task_kind, requires_mcp=requires_mcp)
        base = default_plans.get(executable) or default_plans["clarification_needed"]
        if task_kind == "multi_step_workflow":
            return f"multi_step_workflow is not decomposable yet; collapse to single worker pass as {executable}. {base}"
        return base
