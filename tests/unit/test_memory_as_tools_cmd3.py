# tests/unit/test_memory_as_tools_cmd3.py

"""CMD3: explain_belief / memory_audit / memory_verify (070 + HITL)."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.services.hitl_service import HitlService
from palatium_ai.application.services.memory_verify_service import (
    MEM_VERIFY_TASK_PREFIX,
    MemoryVerifyService,
)
from palatium_ai.domain.mcp.models import MCPToolDescriptor
from palatium_ai.domain.mcp.platform_schemas import PLATFORM_MEMORY_VERIFY_SCHEMA
from palatium_ai.domain.mcp.tool_policy import (
    requires_interrupt_before_call,
    resolve_platform_pin,
)
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.memory.types import (
    MEMORY_ORIGIN_KEY,
    MEMORY_TRUST_KEY,
    resolve_memory_trust,
)
from palatium_ai.infrastructure.hitl.memory_store import InMemoryHitlCardStore
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import make_platform_mcp_registry


@pytest.fixture()
def handler() -> PlatformToolHandler:
    return PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        memory_port=InMemoryMemoryPort(),
    )


@pytest.mark.asyncio()
async def test_explain_belief_returns_provenance_json(handler: PlatformToolHandler) -> None:
    await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-expl",
            "namespace_kind": "user",
            "scope_id": "user-expl",
            "entry_key": "pref-city",
            "value_json": json.dumps(
                {
                    "text": "User lives in Minsk.",
                    "origin": "extract",
                    "trust": "inferred",
                    "source_task_id": "task-extract-99",
                    "thread_id": "thread-chat-7",
                }
            ),
            "memory_type": "fact",
        },
    )

    result = await handler.call_tool(
        "explain_belief",
        {
            "user_id": "user-expl",
            "namespace_kind": "user",
            "scope_id": "user-expl",
            "entry_key": "pref-city",
        },
    )
    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["tool"] == "explain_belief"
    assert payload["entry_key"] == "pref-city"
    assert payload["origin"] == "extract"
    assert payload["trust"] == "inferred"
    assert payload["trust_score"] == 0.5
    assert payload["created_at"]
    assert payload["source"]["task_id"] == "task-extract-99"
    assert payload["source"]["thread_id"] == "thread-chat-7"
    assert "Minsk" in payload["text"]


@pytest.mark.asyncio()
async def test_memory_audit_lists_low_trust_entries(handler: PlatformToolHandler) -> None:
    await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-audit",
            "namespace_kind": "user",
            "scope_id": "user-audit",
            "entry_key": "inferred-fact",
            "value_json": json.dumps(
                {
                    "text": "Maybe likes tea.",
                    "origin": "extract",
                    "trust": "inferred",
                    "source_task_id": "t1",
                }
            ),
        },
    )
    await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-audit",
            "namespace_kind": "user",
            "scope_id": "user-audit",
            "entry_key": "verified-pref",
            "value_json": json.dumps(
                {
                    "text": "Prefers Russian.",
                    "origin": "user_hitl",
                    "trust": "verified",
                    "explicit_write": True,
                }
            ),
            "memory_type": "preference",
        },
    )

    audit = await handler.call_tool(
        "memory_audit",
        {"user_id": "user-audit", "trust_filter": "low", "limit": "32"},
    )
    assert audit.is_error is False
    payload = json.loads(audit.content[0]["text"])
    assert payload["tool"] == "memory_audit"
    keys = {row["entry_key"] for row in payload["entries"]}
    assert "inferred-fact" in keys
    assert "verified-pref" not in keys


@pytest.mark.asyncio()
async def test_memory_verify_pin_requires_hitl() -> None:
    descriptor = MCPToolDescriptor(
        name="memory_verify",
        description="verify",
        input_schema=PLATFORM_MEMORY_VERIFY_SCHEMA,
        side_effect="write",
    )
    pin = resolve_platform_pin(descriptor, server_name="platform")
    assert pin is not None
    assert pin.requires_hitl is True
    assert requires_interrupt_before_call("write", pin=pin) is True


@pytest.mark.asyncio()
async def test_memory_verify_hitl_then_trust_change() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    hitl = HitlService(InMemoryHitlCardStore(), signing_secret="unit-test-hitl-hmac-key-32bytes!!")
    verify = MemoryVerifyService(hitl_service=hitl, mcp_registry=registry)

    await port.put(
        namespace=user_namespace("user-v"),
        key="maybe-fact",
        value={
            "text": "User likes rye bread.",
            "user_id": "user-v",
            MEMORY_ORIGIN_KEY: "extract",
            MEMORY_TRUST_KEY: "inferred",
            "source_task_id": "extract-1",
            "thread_id": "thread-v",
        },
    )

    card = await verify.request_verify(
        thread_id="thread-v",
        owner_user_id="user-v",
        org_id="org-v",
        namespace_kind="user",
        scope_id="user-v",
        entry_key="maybe-fact",
        verdict="confirmed",
    )
    assert card.task_id.startswith(MEM_VERIFY_TASK_PREFIX)
    # Before approve: still inferred.
    before = await port.get(namespace=user_namespace("user-v"), key="maybe-fact")
    assert before is not None
    assert resolve_memory_trust(before) == "inferred"

    outcome = await verify.execute_after_approval(task_id=card.task_id)
    assert outcome["verdict"] == "confirmed"
    after = await port.get(namespace=user_namespace("user-v"), key="maybe-fact")
    assert after is not None
    assert resolve_memory_trust(after) == "verified"


@pytest.mark.asyncio()
async def test_memory_verify_reject_quarantines() -> None:
    port = InMemoryMemoryPort()
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        memory_port=port,
    )
    await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-q",
            "namespace_kind": "user",
            "scope_id": "user-q",
            "entry_key": "bad-fact",
            "value_json": json.dumps(
                {
                    "text": "User owns a private jet.",
                    "origin": "extract",
                    "trust": "inferred",
                }
            ),
        },
    )
    result = await handler.call_tool(
        "memory_verify",
        {
            "user_id": "user-q",
            "namespace_kind": "user",
            "scope_id": "user-q",
            "entry_key": "bad-fact",
            "verdict": "rejected",
        },
    )
    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["trust"] == "quarantined"
    assert payload["trust_score"] == 0.0
    item = await port.get(namespace=user_namespace("user-q"), key="bad-fact")
    assert item is not None
    assert resolve_memory_trust(item) == "quarantined"
