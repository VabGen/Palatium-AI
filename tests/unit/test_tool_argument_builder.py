# tests/unit/test_tool_argument_builder.py

"""Тесты schema-driven builder для MCP tool arguments."""

from __future__ import annotations

import pytest

import palatium_ai.application.services.tool_argument_builder as builder_module

from palatium_ai.application.services.tool_argument_builder import ToolArgumentBuilder
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from tests.conftest import FakeLLMPort


def _descriptor() -> MCPToolDescriptor:
    return MCPToolDescriptor(
        name="search_documents",
        description="Search EDMS documents by query string.",
        inputSchema={
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {
                "query": {"type": "string", "minLength": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )


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


@pytest.mark.asyncio
async def test_tool_argument_builder_returns_validated_arguments() -> None:
    fake_audit = _FakeAuditLogger()
    builder_module.get_audit_logger = lambda: fake_audit
    builder = ToolArgumentBuilder(FakeLLMPort('{"query": "Find the contract in EDMS"}'))

    arguments = await builder.build_arguments(
        descriptor=_descriptor(),
        user_text="Find the contract in EDMS",
        route_plan="Resolve capability and call matching MCP tool.",
        task_kind="tool_execution",
        candidate_capabilities=("search",),
        conversation_id="thread-valid-args",
    )

    assert arguments == {"query": "Find the contract in EDMS"}
    assert fake_audit.calls[-1]["event"] == "tool_argument_builder_validated"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-valid-args"


@pytest.mark.asyncio
async def test_tool_argument_builder_rejects_schema_invalid_arguments() -> None:
    fake_audit = _FakeAuditLogger()
    builder_module.get_audit_logger = lambda: fake_audit
    builder = ToolArgumentBuilder(FakeLLMPort('{"unexpected": "value"}'))

    with pytest.raises(ValueError, match="schema validation"):
        await builder.build_arguments(
            descriptor=_descriptor(),
            user_text="Find the contract in EDMS",
            route_plan="Resolve capability and call matching MCP tool.",
            task_kind="tool_execution",
            candidate_capabilities=("search",),
            conversation_id="thread-invalid-args",
        )
    assert fake_audit.calls[-1]["event"] == "tool_argument_builder_rejected"
    assert fake_audit.calls[-1]["conversation_id"] == "thread-invalid-args"
