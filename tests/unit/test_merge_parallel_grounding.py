"""Parallel merge must preserve Adaptive Grounding flags (no silent feature kill)."""

from __future__ import annotations

from palatium_ai.application.orchestration.agent_bridge import merge_parallel_worker_results
from palatium_ai.domain.agents.researcher import ResearcherOutput, ResearcherTaskResult


def _result(
    *,
    summary: str,
    grounding_degraded: bool = False,
    cannot_answer: bool = False,
    grounding_satisfied: bool = False,
    sources: tuple[str, ...] = (),
) -> ResearcherTaskResult:
    return ResearcherTaskResult(
        task_id="t1",
        agent_role="researcher",
        status="partial" if grounding_degraded or cannot_answer else "success",
        confidence=0.8,
        requires_review=False,
        output=ResearcherOutput(
            summary=summary,
            confidence=0.8,
            sources_used=sources,
            grounding_satisfied=grounding_satisfied,
            grounding_degraded=grounding_degraded,
            cannot_answer_without_source=cannot_answer,
        ),
        grounding_satisfied=grounding_satisfied,
        grounding_degraded=grounding_degraded,
        cannot_answer_without_source=cannot_answer,
    )


def test_merge_propagates_degraded_from_either_worker() -> None:
    merged = merge_parallel_worker_results(
        _result(summary="r", grounding_degraded=True),
        _result(summary="a", sources=("x",), grounding_satisfied=True),
    )
    assert merged.grounding_degraded is True
    assert merged.grounding_satisfied is False
    assert merged.output is not None
    assert merged.output.grounding_degraded is True


def test_merge_propagates_cannot_answer() -> None:
    merged = merge_parallel_worker_results(
        _result(summary="need file", cannot_answer=True, grounding_degraded=True),
        _result(summary="ok"),
    )
    assert merged.cannot_answer_without_source is True
    assert merged.grounding_degraded is True
    assert merged.output is not None
    assert merged.output.cannot_answer_without_source is True


def test_merge_satisfied_only_when_neither_degraded() -> None:
    merged = merge_parallel_worker_results(
        _result(summary="r", sources=("mcp:a",), grounding_satisfied=True),
        _result(summary="a", sources=("mcp:b",), grounding_satisfied=True),
    )
    assert merged.grounding_satisfied is True
    assert merged.grounding_degraded is False
