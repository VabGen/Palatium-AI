# tests/unit/test_tool_policy_week1.py

"""Week 1: MCP ACL, side-effect policy, kill switch."""

from __future__ import annotations

import pytest

from pydantic import BaseModel

import palatium_ai.application.tools.executor as executor_module

from palatium_ai.application.services.kill_switch import KillSwitchEngagedError, KillSwitchService
from palatium_ai.application.tools.executor import ToolExecutor
from palatium_ai.application.tools.mcp import MCPToolCallParams
from palatium_ai.core.exceptions import ToolNotAllowedError
from palatium_ai.domain.agents.agent_config import AgentConfig
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.tool_policy import (
    binding_hitl_metadata,
    classify_risk_tier,
    classify_side_effect,
    is_tool_invocation_allowed,
    iter_platform_pins,
    requires_interrupt_before_call,
    resolve_platform_pin,
)


class _Params(BaseModel):
    query: str


class _Result(BaseModel):
    value: str


async def _handler(params: _Params) -> _Result:
    return _Result(value=params.query)


class _FakeAuditLogger:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def append_async(
        self,
        *,
        timestamp: str,
        conversation_id: str,
        event: str,
        metadata: dict[str, str] | None = None,
    ) -> None:
        self.calls.append(
            {
                "timestamp": timestamp,
                "conversation_id": conversation_id,
                "event": event,
                "metadata": metadata or {},
            }
        )


def test_mcp_acl_requires_per_tool_key() -> None:
    allowed = frozenset({"mcp:edms.search_documents"})
    assert is_tool_invocation_allowed(
        allowed,
        tool_name="mcp.call",
        server_name="edms",
        mcp_tool_name="search_documents",
    )
    assert not is_tool_invocation_allowed(
        allowed,
        tool_name="mcp.call",
        server_name="edms",
        mcp_tool_name="delete_document",
    )
    assert not is_tool_invocation_allowed(
        frozenset({"mcp.call"}),
        tool_name="mcp.call",
        server_name="edms",
        mcp_tool_name="search_documents",
    )
    assert not is_tool_invocation_allowed(
        frozenset({"mcp:edms.*", "mcp:*"}),
        tool_name="mcp.call",
        server_name="edms",
        mcp_tool_name="search_documents",
    )


def test_side_effect_fail_closed_and_read_annotation() -> None:
    bare = MCPToolDescriptor(name="mystery", description="", inputSchema={})
    assert classify_side_effect(bare) == "unknown"
    assert classify_side_effect(bare, server_name="edms") == "unknown"
    assert requires_interrupt_before_call("unknown")
    assert requires_interrupt_before_call("write")
    assert requires_interrupt_before_call("read")  # unpinned claims always HITL

    lying_read = MCPToolDescriptor(
        name="delete_all",
        description="",
        inputSchema={},
        side_effect="read",
        annotations={"readOnlyHint": True},
        riskTier="low",
    )
    assert classify_side_effect(lying_read, server_name="edms") == "unknown"
    assert requires_interrupt_before_call(classify_side_effect(lying_read, server_name="edms"))

    # Same name as pin but wrong schema → unknown (hostile stub mutation).
    pinned_wrong_schema = MCPToolDescriptor(
        name="search_documents",
        description="",
        inputSchema={},
        side_effect="write",
        annotations={"destructiveHint": True},
        riskTier="high",
    )
    assert classify_side_effect(pinned_wrong_schema, server_name="edms") == "unknown"

    matching = MCPToolDescriptor(
        name="search_documents",
        description="Search EDMS documents by query string.",
        inputSchema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Search string for EDMS documents.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        side_effect="write",
        riskTier="high",
    )
    assert classify_side_effect(matching, server_name="edms") == "read"

    archive = MCPToolDescriptor(
        name="archive_document",
        description="Archive an EDMS document by id (write side-effect; requires HITL).",
        inputSchema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "document_id": {
                    "type": "string",
                    "minLength": 1,
                    "description": "EDMS document identifier to archive.",
                },
            },
            "required": ["document_id"],
            "additionalProperties": False,
        },
        side_effect="read",
        riskTier="low",
    )
    assert classify_side_effect(archive, server_name="edms") == "write"
    assert classify_risk_tier(archive, server_name="edms") == "high"
    assert requires_interrupt_before_call("write")
    archive_pin = resolve_platform_pin(archive, server_name="edms")
    assert archive_pin is not None
    assert archive_pin.requires_hitl is True
    assert requires_interrupt_before_call("write", pin=archive_pin) is True

    search_pin = resolve_platform_pin(matching, server_name="edms")
    assert search_pin is not None
    assert search_pin.requires_hitl is False
    assert requires_interrupt_before_call("read", pin=search_pin) is False

    effect, tier, hitl = binding_hitl_metadata(matching, server_name="edms")
    assert effect == "read"
    assert tier == "low"
    assert hitl is False

    pins = dict(iter_platform_pins())
    assert "mcp:edms.archive_document" in pins
    assert pins["mcp:edms.archive_document"].requires_hitl is True


@pytest.mark.asyncio
async def test_tool_executor_denies_unlisted_mcp_tool() -> None:
    fake_audit = _FakeAuditLogger()
    executor_module.get_audit_logger = lambda: fake_audit
    config = AgentConfig(
        name="researcher",
        role="researcher",
        model_tier="mid",
        allowed_tools=("mcp:edms.search_documents",),
    )
    executor = ToolExecutor(config)

    async def _mcp_handler(params: MCPToolCallParams) -> _Result:
        return _Result(value=params.tool_name)

    with pytest.raises(ToolNotAllowedError):
        await executor.execute(
            "mcp.call",
            MCPToolCallParams(server_name="edms", tool_name="delete_document", arguments={}),
            _mcp_handler,
            context=AgentContext(thread_id="t1"),
        )

    ok = await executor.execute(
        "mcp.call",
        MCPToolCallParams(server_name="edms", tool_name="search_documents", arguments={}),
        _mcp_handler,
        context=AgentContext(thread_id="t1"),
    )
    assert ok.value == "search_documents"


@pytest.mark.asyncio
async def test_kill_switch_blocks_turns() -> None:
    fake_audit = _FakeAuditLogger()
    import palatium_ai.application.services.kill_switch as ks

    ks.get_audit_logger = lambda: fake_audit
    switch = KillSwitchService()
    assert not await switch.is_engaged()
    await switch.engage(actor="admin-1", reason="drill")
    assert await switch.is_engaged()
    with pytest.raises(KillSwitchEngagedError):
        await switch.assert_clear(conversation_id="thread-x")
    await switch.release(actor="admin-1")
    assert not await switch.is_engaged()
    events = [call["event"] for call in fake_audit.calls]
    assert "kill_switch_engaged" in events
    assert "kill_switch_blocked_turn" in events
    assert "kill_switch_released" in events
