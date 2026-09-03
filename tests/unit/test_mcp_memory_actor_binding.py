"""call_mcp_tool actor binding for memory writes."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.domain.memory.namespaces import org_namespace
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import PlatformKnowledgeMcpRegistry


@pytest.mark.asyncio
async def test_call_mcp_tool_rebinds_org_scope_to_actor() -> None:
    port = InMemoryMemoryPort()
    registry = PlatformKnowledgeMcpRegistry(
        PlatformToolHandler(knowledge_port=InMemoryKnowledgePort(), memory_port=port)
    )
    outcome = await call_mcp_tool(
        MCPToolCallParams(
            server_name="platform",
            tool_name="save_memory",
            arguments={
                "user_id": "attacker",
                "namespace_kind": "org",
                "scope_id": "org-victim",
                "org_id": "org-victim",
                "entry_key": "leak",
                "value_json": json.dumps({"text": "should land in attacker org"}),
            },
            actor_user_id="attacker",
            actor_org_id="org-attacker",
        ),
        registry,
        conversation_id="thread-actor",
    )
    assert outcome.is_error is False
    victim_hits = await port.search(namespace=org_namespace("org-victim"), query="should land", limit=4)
    attacker_hits = await port.search(namespace=org_namespace("org-attacker"), query="should land", limit=4)
    assert victim_hits == []
    assert attacker_hits


@pytest.mark.asyncio
async def test_call_mcp_tool_rejects_org_write_without_actor() -> None:
    port = InMemoryMemoryPort()
    registry = PlatformKnowledgeMcpRegistry(
        PlatformToolHandler(knowledge_port=InMemoryKnowledgePort(), memory_port=port)
    )
    outcome = await call_mcp_tool(
        MCPToolCallParams(
            server_name="platform",
            tool_name="save_memory",
            arguments={
                "user_id": "attacker",
                "namespace_kind": "org",
                "scope_id": "org-victim",
                "org_id": "org-victim",
                "entry_key": "leak",
                "value_json": json.dumps({"text": "blocked"}),
            },
        ),
        registry,
    )
    assert outcome.is_error is True
    assert "actor_org_id" in outcome.content[0]["text"]


@pytest.mark.asyncio
async def test_call_mcp_tool_search_memory_rebinds_user() -> None:
    port = InMemoryMemoryPort()
    from palatium_ai.domain.memory.namespaces import user_namespace

    await port.put(
        namespace=user_namespace("user-actor"),
        key="k1",
        value={"text": "secret actor fact", "confidence": 0.9},
    )
    await port.put(
        namespace=user_namespace("user-victim"),
        key="k1",
        value={"text": "secret victim fact", "confidence": 0.9},
    )
    registry = PlatformKnowledgeMcpRegistry(
        PlatformToolHandler(knowledge_port=InMemoryKnowledgePort(), memory_port=port)
    )
    outcome = await call_mcp_tool(
        MCPToolCallParams(
            server_name="platform",
            tool_name="search_memory",
            arguments={
                "user_id": "user-victim",
                "query": "secret",
                "org_id": "org-victim",
            },
            actor_user_id="user-actor",
            actor_thread_id="thread-a",
        ),
        registry,
    )
    assert outcome.is_error is False
    blob = json.dumps(outcome.content)
    assert "secret actor fact" in blob
    assert "secret victim fact" not in blob
