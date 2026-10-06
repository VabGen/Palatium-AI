# tests/unit/test_graph_fact_temporal.py

"""Wave M5: GraphFactPolicy, bi-temporal visibility, forget fan-out."""

from __future__ import annotations

import json

from datetime import UTC, datetime

import pytest

from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.domain.graph.temporal import ACTIVE_FACT_AS_OF_PREDICATE, is_fact_active_as_of
from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.domain.memory.namespaces import user_namespace
from palatium_ai.domain.memory.promotion import PromotionCandidate, PromotionThresholds
from palatium_ai.domain.policies.graph_fact import GraphFactPolicy
from palatium_ai.infrastructure.graph.in_memory_graph_write_port import InMemoryGraphWritePort
from palatium_ai.infrastructure.knowledge.in_memory_knowledge_port import InMemoryKnowledgePort
from palatium_ai.infrastructure.mcp.platform_tool_handler import PlatformToolHandler
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort


def test_graph_fact_policy_actions() -> None:
    assert GraphFactPolicy.decide_write(existing_text=None, new_text="a", contains_pii=False) == "create"
    assert GraphFactPolicy.decide_write(existing_text="a", new_text="a", contains_pii=False) == "refresh"
    assert GraphFactPolicy.decide_write(existing_text="a", new_text="b", contains_pii=False) == "supersede"
    assert GraphFactPolicy.decide_write(existing_text="a", new_text="b", contains_pii=True) == "blocked_pii"


def test_is_fact_active_as_of_valid_and_system_time() -> None:
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 6, 1, tzinfo=UTC)
    t2 = datetime(2026, 12, 1, tzinfo=UTC)
    assert is_fact_active_as_of(valid_at=t0, invalid_at=None, expired_at=None, as_of=t1) is True
    assert is_fact_active_as_of(valid_at=t0, invalid_at=t1, expired_at=None, as_of=t1) is False
    assert is_fact_active_as_of(valid_at=t0, invalid_at=None, expired_at=t1, as_of=t1) is False
    assert is_fact_active_as_of(valid_at=t2, invalid_at=None, expired_at=None, as_of=t1) is False


def test_active_fact_predicate_binds_as_of() -> None:
    assert "$as_of" in ACTIVE_FACT_AS_OF_PREDICATE
    assert "$user_id" in ACTIVE_FACT_AS_OF_PREDICATE
    assert "expired_at" in ACTIVE_FACT_AS_OF_PREDICATE
    assert "datetime($as_of)" in ACTIVE_FACT_AS_OF_PREDICATE


@pytest.mark.asyncio()
async def test_in_memory_supersede_keeps_history() -> None:
    port = InMemoryGraphWritePort()
    first = await port.upsert_fact(
        GraphFactUpsert(user_id="u1", entry_key="k", text="v1", kind="fact", importance=0.9)
    )
    second = await port.upsert_fact(
        GraphFactUpsert(user_id="u1", entry_key="k", text="v2", kind="fact", importance=0.9)
    )
    assert first != second
    active = port.get_active_fact(user_id="u1", entry_key="k")
    assert active is not None
    assert active.text == "v2"
    assert active.version == 2
    rows = port.list_facts_as_of(user_id="u1", as_of=datetime.now(UTC))
    assert len(rows) == 1
    assert rows[0].text == "v2"
    third = await port.upsert_fact(
        GraphFactUpsert(user_id="u1", entry_key="k", text="v2", kind="fact", importance=0.5)
    )
    assert third == second


@pytest.mark.asyncio()
async def test_expire_hides_fact_from_temporal_query() -> None:
    port = InMemoryGraphWritePort()
    await port.upsert_fact(
        GraphFactUpsert(user_id="u1", entry_key="gone", text="forget me", kind="fact")
    )
    assert await port.expire_fact(user_id="u1", entry_key="gone") is True
    assert port.get_active_fact(user_id="u1", entry_key="gone") is None
    assert port.list_facts_as_of(user_id="u1", as_of=datetime.now(UTC)) == []


@pytest.mark.asyncio()
async def test_forget_memory_fan_out_expires_graph_fact() -> None:
    memory = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        memory_port=memory,
        graph_write=graph,
    )
    await handler.call_tool(
        "save_memory",
        {
            "user_id": "user-fan",
            "namespace_kind": "user",
            "scope_id": "user-fan",
            "entry_key": "temp-fact",
            "value_json": json.dumps({"text": "Temporary onboarding note.", "confidence": 0.8}),
        },
    )
    await graph.upsert_fact(
        GraphFactUpsert(
            user_id="user-fan",
            entry_key="temp-fact",
            text="Temporary onboarding note.",
            kind="fact",
        )
    )
    forget = await handler.call_tool(
        "forget_memory",
        {
            "user_id": "user-fan",
            "namespace_kind": "user",
            "scope_id": "user-fan",
            "entry_key": "temp-fact",
        },
    )
    assert forget.is_error is False
    payload = json.loads(forget.content[0]["text"])
    assert payload["forgotten"] is True
    assert payload["graph_expired"] is True
    assert graph.get_active_fact(user_id="user-fan", entry_key="temp-fact") is None


@pytest.mark.asyncio()
async def test_promotion_skips_blocked_pii_supersede() -> None:
    memory = InMemoryMemoryPort()
    graph = InMemoryGraphWritePort()
    ns = user_namespace("alice")
    await memory.put(
        namespace=ns,
        key="pii-key",
        value={
            "text": "new secret phone +1-555-0100",
            "kind": "fact",
            "confidence": 0.95,
            "importance": 0.9,
            "contains_pii": True,
        },
    )
    for _ in range(3):
        await memory.bump_access(namespace=ns, key="pii-key")
    # Seed prior PII fact with different text → promote must not auto-flip.
    await graph.upsert_fact(
        GraphFactUpsert(
            user_id="alice",
            entry_key="pii-key",
            text="old secret phone +1-555-0000",
            kind="fact",
            contains_pii=True,
        )
    )
    service = MemoryPromotionService(
        memory=memory,
        graph_write=graph,
        thresholds=PromotionThresholds(min_access_frequency=3, min_importance=0.7),
    )
    promoted = await service.run_batch(user_id="alice", limit=8)
    assert promoted == 0
    active = graph.get_active_fact(user_id="alice", entry_key="pii-key")
    assert active is not None
    assert "0000" in active.text


@pytest.mark.asyncio()
async def test_graph_query_injects_as_of() -> None:
    from palatium_ai.infrastructure.graph.in_memory_graph_port import InMemoryGraphPort

    captured: dict[str, object] = {}

    class _CapturePort(InMemoryGraphPort):
        async def query(self, command):  # type: ignore[no-untyped-def]
            captured["params"] = dict(command.params)
            return await super().query(command)

    handler = PlatformToolHandler(
        knowledge_port=InMemoryKnowledgePort(),
        graph_port=_CapturePort(),
    )
    result = await handler.call_tool(
        "graph_query",
        {
            "user_id": "user-1",
            "cypher": (
                "MATCH (f:MemoryFact) WHERE "
                + ACTIVE_FACT_AS_OF_PREDICATE
                + " RETURN f.text AS text LIMIT $lim"
            ),
            "params_json": json.dumps({"lim": 5, "as_of": "should-not-win"}),
            "as_of": "2026-03-15T12:00:00Z",
        },
    )
    assert result.is_error is False
    payload = json.loads(result.content[0]["text"])
    assert payload["as_of"] == "2026-03-15T12:00:00Z"
    assert captured["params"]["user_id"] == "user-1"
    assert captured["params"]["as_of"] == "2026-03-15T12:00:00Z"


def test_promotion_candidate_carries_contains_pii() -> None:
    candidate = PromotionCandidate(
        namespace=("user", "u1"),
        entry_key="k",
        text="x",
        importance=0.9,
        access_frequency=3,
        user_id="u1",
        confidence=0.9,
        contains_pii=True,
    )
    assert candidate.contains_pii is True
