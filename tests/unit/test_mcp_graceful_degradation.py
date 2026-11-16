"""Level 5: a downed MCP module degrades the answer instead of failing the turn (035).

Three links are asserted separately so a regression names the broken one:
1. the registry wraps transport failures as ``McpServerUnavailableError`` (port contract);
2. the Host call turns that into an outcome with a machine code, not a generic error;
3. the Formatter gate renders degradation copy — with local uploads it offers them.
"""

from __future__ import annotations

from typing import cast

import pytest

from palatium_ai.application.agents.formatter.messages import localized_message
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.mcp_capabilities import MCPCapabilityIndex
from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.agents.researcher import MCP_SERVER_UNAVAILABLE
from palatium_ai.domain.mcp.models import MCPToolCall, MCPToolResult
from palatium_ai.domain.policies import EffectiveRoutingIntent
from palatium_ai.domain.ports.mcp import McpServerUnavailableError
from palatium_ai.infrastructure.mcp.registry import MCPCircuitOpenError


class _TransportDownRegistry:
    """Registry whose remote server always fails at the transport layer.

    Mirrors the real adapter contract: transport problems surface as the port's
    ``McpServerUnavailableError``, never as a leaked httpx exception (035).
    """

    def list_servers(self) -> list[str]:
        return ["edms"]

    async def call_tool(
        self,
        server_name: str,
        tool_call: MCPToolCall,
        *,
        allow_unpinned: bool = False,
    ) -> MCPToolResult:
        raise McpServerUnavailableError(server_name)

    async def list_tools(self, server_name: str) -> list[object]:
        raise McpServerUnavailableError(server_name)

    async def list_tool_summaries(self, server_name: str) -> list[object]:
        raise McpServerUnavailableError(server_name)

    async def get_tool(self, server_name: str, tool_name: str) -> None:
        raise McpServerUnavailableError(server_name)


def test_circuit_open_error_is_a_port_contract_error() -> None:
    """Callers catch one base type, whatever the adapter raised."""
    assert isinstance(MCPCircuitOpenError("edms", retry_after_seconds=5.0), McpServerUnavailableError)


@pytest.mark.asyncio()
async def test_transport_failure_becomes_a_machine_code() -> None:
    outcome = await call_mcp_tool(
        MCPToolCallParams(server_name="edms", tool_name="search_documents"),
        cast("object", _TransportDownRegistry()),  # type: ignore[arg-type]  # protocol stub
    )
    assert outcome.is_error is True
    assert outcome.error_code == "server_unavailable"


@pytest.mark.asyncio()
async def test_degraded_discovery_is_observable() -> None:
    index = MCPCapabilityIndex(cast("object", _TransportDownRegistry()))  # type: ignore[arg-type]
    assert await index.discover(force_refresh=True) == []
    assert index.degraded_servers() == ("edms",)


def _degraded_state(*, focus: str) -> AgentGraphState:
    from uuid import uuid4

    from palatium_ai.domain.attachments.context import AttachmentContextBlock, AttachmentTurnContext

    block = AttachmentContextBlock(
        attachment_id=uuid4(),
        filename="report.txt",
        source="attachment:report.txt",
        fenced_text='<untrusted_content source="attachment:report.txt">\nТекст\n</untrusted_content>',
        action="allow",
        page_count=1,
    )
    return cast(
        "AgentGraphState",
        {
            "task_id": "task-degraded",
            "thread_id": "thread-degraded",
            "user_text": "Поищи в корпоративной базе",
            "attachment_context": AttachmentTurnContext(blocks=(block,)),
            "classification": IntentTaskResult(
                task_id="task-degraded",
                agent_role="intent_classifier",
                status="success",
                confidence=0.9,
                output=IntentClassifierOutput(
                    task_kind="knowledge_request",
                    requires_mcp=True,
                    attachment_focus=focus,  # type: ignore[arg-type]  # closed Literal under test
                    confidence=0.9,
                    reasoning="needs corporate base",
                ),
            ),
            "routing_intent": EffectiveRoutingIntent(
                task_kind="knowledge_request",
                requires_mcp=True,
                reasoning="needs corporate base",
            ),
        },
    )


def test_local_files_are_offered_only_when_in_scope() -> None:
    """The degraded answer mentions uploads only if this turn is actually about them."""
    in_scope = _degraded_state(focus="current_uploads")
    out_of_scope = _degraded_state(focus="none")

    def offerable(state: AgentGraphState) -> bool:
        from palatium_ai.application.orchestration import selectors

        return selectors.uploads_in_scope(state) and bool(selectors.attachment_blocks(state))

    assert offerable(in_scope) is True
    assert offerable(out_of_scope) is False


def test_degradation_copy_offers_local_files() -> None:
    with_files = localized_message("ru", f"{MCP_SERVER_UNAVAILABLE}_with_files")
    without_files = localized_message("ru", MCP_SERVER_UNAVAILABLE)
    assert with_files is not None
    assert without_files is not None
    assert "файлы" in with_files
    assert "недоступен" in without_files
    assert "файлы" not in without_files


def test_degradation_copy_is_localized() -> None:
    assert "unavailable" in localized_message("en", MCP_SERVER_UNAVAILABLE)
    assert "недоступен" in localized_message("ru", MCP_SERVER_UNAVAILABLE)
