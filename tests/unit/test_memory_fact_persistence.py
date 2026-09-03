"""MemoryFactPersistenceService routes facts through save_memory MCP."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_consolidation import ConsolidationJob
from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
from palatium_ai.domain.agents.memory_keeper import MemoryFactCandidate
from palatium_ai.domain.memory.namespaces import org_namespace, user_namespace
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import make_platform_mcp_registry


@pytest.mark.asyncio
async def test_persist_facts_uses_save_memory_mcp() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = ConsolidationJob(thread_id="thread-1", task_id="task-1", user_id="user-1")
    fact = MemoryFactCandidate(
        text="User prefers concise bullet lists",
        kind="preference",
        confidence=0.92,
        key_hint="pref-bullets",
    )
    stored = await service.persist_facts(job=job, facts=(fact,))
    assert stored == 1
    hits = await port.search(namespace=user_namespace("user-1"), query="bullet", limit=4)
    assert hits
    assert hits[0]["kind"] == "preference"


@pytest.mark.asyncio
async def test_persist_facts_maps_entity_to_org_namespace() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = ConsolidationJob(thread_id="thread-2", task_id="task-2", user_id="user-2", org_id="org-x")
    fact = MemoryFactCandidate(
        text="Acme billing contact is Petrov",
        kind="entity",
        confidence=0.85,
        key_hint="acme-billing",
    )
    stored = await service.persist_facts(job=job, facts=(fact,))
    assert stored == 1
    hits = await port.search(namespace=org_namespace("org-x"), query="Petrov", limit=4)
    assert hits
    assert hits[0]["kind"] == "entity"


@pytest.mark.asyncio
async def test_persist_facts_blocks_secrets() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = ConsolidationJob(thread_id="thread-sec", task_id="task-sec", user_id="user-sec")
    fact = MemoryFactCandidate(
        text="api key sk-abcdefghijklmnopqrstuvwxyz012345",
        kind="preference",
        confidence=0.9,
        key_hint="secret",
    )
    stored = await service.persist_facts(job=job, facts=(fact,))
    assert stored == 0
    hits = await port.search(namespace=user_namespace("user-sec"), query="sk-", limit=4)
    assert hits == []


@pytest.mark.asyncio
async def test_persist_facts_marks_pii_from_text() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = ConsolidationJob(thread_id="thread-pii", task_id="task-pii", user_id="user-pii")
    fact = MemoryFactCandidate(
        text="User email is alice@example.com",
        kind="preference",
        confidence=0.9,
        key_hint="email",
    )
    stored = await service.persist_facts(job=job, facts=(fact,))
    assert stored == 1
    item = await port.get(namespace=user_namespace("user-pii"), key="add:email")
    assert item is not None
    assert item.get("contains_pii") is True or item.get("text") == "[PII]"
