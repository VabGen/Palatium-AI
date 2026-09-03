# tests/unit/test_platform_memory_mcp.py

"""Platform memory MCP tools → MemoryPort wiring."""

from __future__ import annotations

import json

import pytest

from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


@pytest.fixture
def handler() -> PlatformToolHandler:
    return PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        memory_port=InMemoryMemoryPort(),
    )


@pytest.mark.asyncio
async def test_save_and_search_memory(handler: PlatformToolHandler) -> None:
    save = await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-1",
            "namespace_kind": "thread",
            "scope_id": "thread-42",
            "entry_key": "pref-lang",
            "value_json": json.dumps({"text": "User prefers Russian responses.", "confidence": 0.9}),
            "memory_type": "preference",
        },
    )
    assert save.is_error is False

    search = await handler.call_tool(
        "search_memory",
        {"user_id": "user-1", "query": "Russian", "thread_id": "thread-42", "limit": "5"},
    )
    assert search.is_error is False
    payload = json.loads(search.content[0]["text"])
    assert payload["hit_count"] >= 1
    assert "Russian" in payload["hits"][0]["text"]


@pytest.mark.asyncio
async def test_forget_memory_removes_entry(handler: PlatformToolHandler) -> None:
    await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-2",
            "namespace_kind": "user",
            "scope_id": "user-2",
            "entry_key": "temp-fact",
            "value_json": json.dumps({"text": "Temporary onboarding note.", "confidence": 0.8}),
        },
    )
    forget = await handler.call_tool(
        "forget_memory",
        {
            "user_id": "user-2",
            "namespace_kind": "user",
            "scope_id": "user-2",
            "entry_key": "temp-fact",
        },
    )
    assert forget.is_error is False
    payload = json.loads(forget.content[0]["text"])
    assert payload["forgotten"] is True

    search = await handler.call_tool(
        "search_memory",
        {"user_id": "user-2", "query": "onboarding", "limit": "5"},
    )
    search_payload = json.loads(search.content[0]["text"])
    assert search_payload["hit_count"] == 0


@pytest.mark.asyncio
async def test_save_memory_rejects_org_without_matching_claim(handler: PlatformToolHandler) -> None:
    result = await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-1",
            "namespace_kind": "org",
            "scope_id": "org-x",
            "entry_key": "x",
            "value_json": json.dumps({"text": "blocked"}),
        },
    )
    assert result.is_error is True


@pytest.mark.asyncio
async def test_save_memory_org_with_matching_claim(handler: PlatformToolHandler) -> None:
    result = await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-1",
            "namespace_kind": "org",
            "scope_id": "org-ok",
            "org_id": "org-ok",
            "entry_key": "entity-1",
            "value_json": json.dumps({"text": "Org fact", "confidence": 0.8}),
        },
    )
    assert result.is_error is False


@pytest.mark.asyncio
async def test_save_memory_rejects_mismatched_user_scope(handler: PlatformToolHandler) -> None:
    result = await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-1",
            "namespace_kind": "user",
            "scope_id": "user-other",
            "entry_key": "x",
            "value_json": json.dumps({"text": "blocked"}),
        },
    )
    assert result.is_error is True


@pytest.mark.asyncio
async def test_save_memory_sets_pii_from_text(handler: PlatformToolHandler) -> None:
    save = await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-pii",
            "namespace_kind": "user",
            "scope_id": "user-pii",
            "entry_key": "email",
            "value_json": json.dumps({"text": "Contact bob@example.com", "contains_pii": False}),
        },
    )
    assert save.is_error is False
    item = await handler._memory.get(  # noqa: SLF001
        namespace=("user", "user-pii"),
        key="email",
    )
    assert item is not None
    # masked on read when contains_pii — placeholder or flag present
    assert item.get("contains_pii") is True or item.get("text") == "[PII]"


@pytest.mark.asyncio
async def test_consolidate_memory_without_worker_returns_error(handler: PlatformToolHandler) -> None:
    result = await handler.call_tool(
        "consolidate_memory",
        {"user_id": "user-3", "thread_id": "thread-3"},
    )
    assert result.is_error is True
