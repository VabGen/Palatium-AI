"""MemoryFactPersistenceService routes facts through save_memory MCP."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_extract import MemoryExtractJob
from palatium_ai.application.services.memory_fact_persistence import (
    MemoryFactPersistenceService,
    _memory_key,
)
from palatium_ai.domain.agents.memory_keeper import MemoryFactCandidate
from palatium_ai.domain.memory.namespaces import org_namespace, user_namespace
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import make_platform_mcp_registry


def test_memory_key_avoids_colon_uri_scheme_shape() -> None:
    """MCP argument_policy treats ``add:slug`` as denied URI scheme ``add``."""
    keyed = _memory_key("pref-bullets", "text")
    hashed = _memory_key(None, "some durable fact text")
    assert keyed == "add-pref-bullets"
    assert ":" not in keyed
    assert hashed.startswith("add-")
    assert ":" not in hashed


def test_memory_key_is_deterministic_across_retries() -> None:
    """M3 audit E3: at-least-once delivery must upsert, not duplicate."""
    first = _memory_key(None, "User prefers concise bullet lists")
    second = _memory_key(None, "User prefers concise bullet lists")
    assert first == second
    # Same fact with different surrounding whitespace is still the same key.
    assert _memory_key(None, "  User prefers   concise bullet lists\n") == first
    # Different text must stay a different fact.
    assert _memory_key(None, "User prefers long prose") != first


@pytest.mark.asyncio()
async def test_reclaimed_job_does_not_duplicate_memory_entries() -> None:
    """A retried extract job re-persists the same facts under the same keys (E3)."""
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = MemoryExtractJob(thread_id="thread-retry", task_id="task-retry", user_id="user-retry")
    fact = MemoryFactCandidate(
        text="User prefers concise bullet lists",
        kind="preference",
        confidence=0.9,
        key_hint=None,
    )

    assert await service.persist_facts(job=job, facts=(fact,)) == 1
    assert await service.persist_facts(job=job, facts=(fact,)) == 1

    hits = await port.search(namespace=user_namespace("user-retry"), query="bullet", limit=10)
    assert len(hits) == 1


@pytest.mark.asyncio()
async def test_persist_facts_uses_save_memory_mcp() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = MemoryExtractJob(thread_id="thread-1", task_id="task-1", user_id="user-1")
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


@pytest.mark.asyncio()
async def test_persist_facts_maps_entity_to_org_namespace() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = MemoryExtractJob(thread_id="thread-2", task_id="task-2", user_id="user-2", org_id="org-x")
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


@pytest.mark.asyncio()
async def test_persist_facts_blocks_secrets() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = MemoryExtractJob(thread_id="thread-sec", task_id="task-sec", user_id="user-sec")
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


@pytest.mark.asyncio()
async def test_persist_facts_marks_pii_from_text() -> None:
    port = InMemoryMemoryPort()
    registry = make_platform_mcp_registry(memory_port=port)
    service = MemoryFactPersistenceService(registry)
    job = MemoryExtractJob(thread_id="thread-pii", task_id="task-pii", user_id="user-pii")
    fact = MemoryFactCandidate(
        text="User email is alice@example.com",
        kind="preference",
        confidence=0.9,
        key_hint="email",
    )
    stored = await service.persist_facts(job=job, facts=(fact,))
    assert stored == 1
    item = await port.get(namespace=user_namespace("user-pii"), key="add-email")
    assert item is not None
    assert item.get("contains_pii") is True or item.get("text") == "[PII]"
