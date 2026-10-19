"""ExecutionPlanner — a thread file re-read binds platform.read_attachment (055, 070)."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput


@pytest.fixture(autouse=True)
def _enable_file_reread(monkeypatch: pytest.MonkeyPatch) -> None:
    """Full rollout for the structural tests; the gate itself is covered below."""
    from palatium_ai.core.config import get_settings

    monkeypatch.setenv("ATTACHMENTS_FILE_REREAD_PCT", "100")
    get_settings.cache_clear()


def _input(**overrides: object) -> ContextWeaverInput:
    payload: dict[str, object] = {
        "task_id": "t1",
        "user_text": "а из БД взять этот файл и ещё раз прочитать",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "route_plan": "re-read the upload from storage",
        "requires_mcp": True,
        "has_attachment_context": False,
        "file_reference": "thread_file",
    }
    payload.update(overrides)
    return ContextWeaverInput(**payload)  # type: ignore[arg-type]  # test builder (017)


@pytest.mark.asyncio()
async def test_thread_file_binds_direct_read_attachment() -> None:
    bundle = await ExecutionPlanner(capability_index=None).build(_input())

    step = bundle.steps[0]
    assert step.strategy == "direct_tool_call"
    assert step.requires_tool_call is True
    assert (step.server_name, step.tool_name) == ("platform", "read_attachment")
    assert bundle.requires_tool_call is True


@pytest.mark.asyncio()
async def test_fresh_upload_owns_the_turn_over_a_thread_reference() -> None:
    """A new fence already carries its own text; storage must not be re-read (055)."""
    bundle = await ExecutionPlanner(capability_index=None).build(_input(has_attachment_context=True))

    step = bundle.steps[0]
    assert step.tool_name != "read_attachment"
    assert step.strategy == "reason_only"
    assert step.requires_tool_call is False


@pytest.mark.asyncio()
async def test_axis_none_keeps_the_retrieval_path() -> None:
    bundle = await ExecutionPlanner(capability_index=None).build(
        _input(file_reference="none", requires_mcp=False),
    )

    step = bundle.steps[0]
    assert step.strategy == "retrieve_then_reason"
    assert step.tool_name == "search_knowledge"


@pytest.mark.asyncio()
async def test_non_researcher_route_does_not_re_read() -> None:
    bundle = await ExecutionPlanner(capability_index=None).build(_input(route="formatter"))

    step = bundle.steps[0]
    assert step.strategy == "format_only"
    assert step.tool_name is None


@pytest.mark.asyncio()
async def test_re_read_plan_carries_an_explainable_rationale() -> None:
    bundle = await ExecutionPlanner(capability_index=None).build(_input())

    rationale = bundle.steps[0].rationale or ""
    assert rationale
    assert "thread file" in rationale.lower()


@pytest.mark.asyncio()
async def test_rollout_off_keeps_the_pre_existing_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    """PCT=0 is the one-variable rollback: the turn must not dispatch the read (055)."""
    from palatium_ai.core.config import get_settings

    monkeypatch.setenv("ATTACHMENTS_FILE_REREAD_PCT", "0")
    get_settings.cache_clear()

    bundle = await ExecutionPlanner(capability_index=None).build(_input())

    step = bundle.steps[0]
    assert step.tool_name is None
    assert step.strategy == "reason_only"
    assert step.requires_tool_call is False
