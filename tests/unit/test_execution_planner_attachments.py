"""ExecutionPlanner — prefer attachment OCR over search_knowledge."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.execution_planner import ExecutionPlanner
from palatium_ai.domain.agents.context_weaver import ContextWeaverInput


@pytest.mark.asyncio()
async def test_attachment_context_skips_search_knowledge() -> None:
    planner = ExecutionPlanner(capability_index=None)
    task_input = ContextWeaverInput(
        task_id="t1",
        user_text="дай полный текст из файла",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer from upload",
        requires_mcp=False,
        has_attachment_context=True,
    )
    bundle = await planner.build(task_input)
    assert bundle.selected_strategy == "reason_only"
    assert bundle.requires_tool_call is False


@pytest.mark.asyncio()
async def test_knowledge_without_attachment_still_retrieves() -> None:
    planner = ExecutionPlanner(capability_index=None)
    task_input = ContextWeaverInput(
        task_id="t1",
        user_text="что такое RLS",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="retrieve",
        requires_mcp=False,
        has_attachment_context=False,
    )
    bundle = await planner.build(task_input)
    assert bundle.selected_strategy == "retrieve_then_reason"
    assert bundle.requires_tool_call is True
