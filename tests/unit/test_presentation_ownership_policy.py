"""Presentation ownership policy — single-writer axis (P1a)."""

from __future__ import annotations

from palatium_ai.domain.policies.presentation import PresentationOwnershipPolicy


def _decide(**overrides: object) -> tuple[str, str]:
    payload: dict[str, object] = {
        "task_kind": "knowledge_request",
        "transformation": "none",
        "requires_user_choice": False,
        "underspecification_kind": "none",
        "candidate_capabilities": (),
        "revision_requested": False,
        "response_shape": "auto",
        "rollout_allows": True,
    }
    payload.update(overrides)
    decision = PresentationOwnershipPolicy.decide(**payload)  # type: ignore[arg-type]
    return decision.owner, decision.reason


def test_knowledge_answer_is_worker_owned() -> None:
    assert _decide() == ("worker", "eligible")


def test_tool_and_multi_step_are_worker_owned() -> None:
    assert _decide(task_kind="tool_execution")[0] == "worker"
    assert _decide(task_kind="multi_step_workflow")[0] == "worker"


def test_non_worker_task_kinds_stay_formatter_owned() -> None:
    for kind in ("response_formatting", "social_conversation", "clarification_needed", "capability_discovery"):
        assert _decide(task_kind=kind) == ("formatter", "task_kind")


def test_rollout_exclusion_never_owns() -> None:
    assert _decide(rollout_allows=False) == ("formatter", "rollout_excluded")


def test_composition_requests_stay_formatter_owned() -> None:
    cases = {
        "restructure_requested": {"transformation": "restructure"},
        "requires_user_choice": {"requires_user_choice": True},
        "underspecified": {"underspecification_kind": "open_text"},
        "revision_requested": {"revision_requested": True},
        "shape_requested": {"response_shape": "comparison_table"},
        "verbatim_requested": {"candidate_capabilities": ("verbatim_extraction",)},
    }
    for expected_reason, overrides in cases.items():
        assert _decide(**overrides) == ("formatter", expected_reason)


def test_expand_rewrite_remain_worker_owned() -> None:
    for transformation in ("expand", "shorten", "rewrite"):
        assert _decide(transformation=transformation)[0] == "worker"
