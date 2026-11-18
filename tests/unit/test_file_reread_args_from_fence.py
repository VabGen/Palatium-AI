"""Forced read_attachment args prefer UUIDs already in truncated fences."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from palatium_ai.application.agents.researcher.mcp_path import (
    McpPathDeps,
    _build_file_reread_arguments,
)
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.attachments.fence_source import attachment_fence_source
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output

_ID = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class _NoResolver:
    """Resolver must not be consulted when the fence already names the id."""

    async def resolve(self, **_kwargs: object) -> object:
        raise AssertionError("resolver must not run when fence carries attachment_id")


@pytest.mark.asyncio()
async def test_build_file_reread_args_uses_fence_uuid() -> None:
    fence = wrap_untrusted_tool_output(
        "head\n… [attachment body truncated] …\ntail",
        source=attachment_fence_source(attachment_id=_ID, filename="big.pdf"),
    )
    packet = ContextPacket(
        task_id="t1",
        user_text="суммируй раздел 3",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="read",
        requires_mcp=True,
        execution_plan=ToolExecutionPlan(
            strategy="direct_tool_call",
            capability="attachments",
            server_name="platform",
            tool_name="read_attachment",
            requires_tool_call=True,
            rationale="test",
        ),
        context_summary="trunc",
        untrusted_context=fence,
    )
    task_input = ResearcherInput(task_id="t1", context_packet=packet)
    deps = McpPathDeps(
        config=AgentConfig(
            name="researcher",
            role="researcher",
            model_tier="mid",
            temperature=0.0,
        ),
        harness=object(),  # type: ignore[arg-type]
        mcp_registry=object(),  # type: ignore[arg-type]
        capability_index=object(),  # type: ignore[arg-type]
        tool_executor=object(),  # type: ignore[arg-type]
        argument_builder=object(),  # type: ignore[arg-type]
        mcp_tool_call_repository=None,
        agent_role="researcher",
        file_reference_resolver=_NoResolver(),  # type: ignore[arg-type]
    )
    context = AgentContext(thread_id="thread-1", user_id="user-1")
    args = await _build_file_reread_arguments(deps, task_input, context, "read_attachment", uuid4())
    assert isinstance(args, dict)
    assert args["attachment_id"] == str(_ID)
    assert args["user_id"] == "user-1"
