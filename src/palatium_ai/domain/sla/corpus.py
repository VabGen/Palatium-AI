# src/palatium_ai/domain/sla/corpus.py

"""Structural benchmark corpus (task_kind × axis), not phrase hardcoding."""

from __future__ import annotations

from dataclasses import dataclass

from palatium_ai.domain.agents.intent import TaskKind


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One synthetic turn labeled by domain axes."""

    case_id: str
    task_kind: TaskKind
    requires_mcp: bool
    user_text: str


def build_benchmark_corpus(*, size: int = 100) -> tuple[BenchmarkCase, ...]:
    """
    Expand a small structural template set to `size` cases.

    Texts are placeholders keyed by axes — Intent/Supervisor policies classify by
    contract, not by matching these strings in production code.
    """
    if size < 1:
        raise ValueError("size must be >= 1")

    templates: tuple[tuple[TaskKind, bool, str], ...] = (
        ("social_conversation", False, "axis=social turn={n}"),
        ("capability_discovery", False, "axis=capability turn={n}"),
        ("knowledge_request", False, "axis=knowledge turn={n}"),
        ("tool_execution", True, "axis=tool_execution mcp=1 turn={n}"),
        ("clarification_needed", False, "axis=clarification turn={n}"),
        ("response_formatting", False, "axis=format turn={n}"),
        ("multi_step_workflow", True, "axis=workflow mcp=1 turn={n}"),
        ("knowledge_request", True, "axis=knowledge mcp=1 turn={n}"),
    )

    cases: list[BenchmarkCase] = []
    for index in range(size):
        kind, requires_mcp, pattern = templates[index % len(templates)]
        n = index + 1
        cases.append(
            BenchmarkCase(
                case_id=f"bench-{n:04d}",
                task_kind=kind,
                requires_mcp=requires_mcp,
                user_text=pattern.format(n=n),
            )
        )
    return tuple(cases)
