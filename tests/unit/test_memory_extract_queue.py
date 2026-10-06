# tests/unit/test_memory_extract_queue.py

"""Durable extract queue + axis split (Wave M3)."""

from __future__ import annotations

import asyncio
import json

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from palatium_ai.application.services.memory_extract import MemoryExtractService
from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.infrastructure.memory.extract_job_queue import InMemoryExtractJobQueue
from palatium_ai.infrastructure.memory.in_memory_store import InMemoryMemoryPort
from tests.conftest import FakeLLMPort, make_platform_mcp_registry


class _FakeDialog:
    def __init__(self) -> None:
        self._turns = [("user", "Запомни предпочтение таблиц"), ("assistant", "Ок")]

    async def append_turn(self, **_kwargs: object) -> DialogTurn:
        raise NotImplementedError

    async def list_recent_turns(self, *, thread_id: str, limit: int = 12) -> DialogTurnWindow:
        turns = tuple(
            DialogTurn(
                id=uuid4(),
                thread_id=thread_id,
                role=role,  # type: ignore[arg-type]
                content=content,
                seq=idx,
                created_at=datetime.now(UTC),
            )
            for idx, (role, content) in enumerate(self._turns[:limit])
        )
        return DialogTurnWindow(thread_id=thread_id, turns=turns, limit=limit)


@pytest.mark.asyncio()
async def test_enqueue_idempotent_same_thread_task() -> None:
    queue = InMemoryExtractJobQueue(max_queue=8)
    assert await queue.enqueue(thread_id="t1", task_id="job-1", user_id="u1")
    assert await queue.enqueue(thread_id="t1", task_id="job-1", user_id="u1")
    stats = await queue.stats()
    assert stats.depth == 1


@pytest.mark.asyncio()
async def test_queue_full_rejects() -> None:
    queue = InMemoryExtractJobQueue(max_queue=1)
    assert await queue.enqueue(thread_id="t1", task_id="a")
    assert not await queue.enqueue(thread_id="t1", task_id="b")


@pytest.mark.asyncio()
async def test_lease_expiry_allows_redelivery_without_dup_row() -> None:
    queue = InMemoryExtractJobQueue(max_queue=8, lease_seconds=1, max_attempts=3)
    assert await queue.enqueue(thread_id="t1", task_id="reclaim-1", user_id="u1")
    first = await queue.claim()
    assert first is not None
    # Simulate kill mid-extract: lease expires, same logical job reclaimable.
    expired = first.model_copy(update={"leased_until": datetime.now(UTC) - timedelta(seconds=1)})
    queue._rows[first.id] = expired
    second = await queue.claim()
    assert second is not None
    assert second.id == first.id
    assert second.attempts == 2
    await queue.complete(second.id)
    assert (await queue.claim()) is None


@pytest.mark.asyncio()
async def test_fail_moves_to_dead_letter() -> None:
    queue = InMemoryExtractJobQueue(max_queue=8, max_attempts=2)
    await queue.enqueue(thread_id="t1", task_id="dead-1")
    job = await queue.claim()
    assert job is not None
    await queue.fail(job.id, error="boom1")
    # Backoff: force available for second attempt.
    pending = queue._rows[job.id]
    queue._rows[job.id] = pending.model_copy(
        update={"available_at": datetime.now(UTC) - timedelta(seconds=1)}
    )
    job2 = await queue.claim()
    assert job2 is not None
    await queue.fail(job2.id, error="boom2")
    stats = await queue.stats()
    assert stats.dead == 1
    assert await queue.claim() is None


@pytest.mark.asyncio()
async def test_extract_worker_does_not_call_promote() -> None:
    port = InMemoryMemoryPort()
    payload = {
        "facts": [
            {
                "text": "User prefers tables",
                "kind": "preference",
                "confidence": 0.9,
                "key_hint": "pref-tables",
            }
        ],
        "reasoning": "pref",
    }
    harness = Harness(llm=FakeLLMPort(json.dumps(payload)))
    keeper = MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG)
    registry = make_platform_mcp_registry(memory_port=port)
    queue = InMemoryExtractJobQueue()
    service = MemoryExtractService(
        harness=harness,
        memory_keeper=keeper,
        memory_port=port,
        memory_persistence=MemoryFactPersistenceService(registry),
        job_queue=queue,
        dialog_turn_store=_FakeDialog(),  # type: ignore[arg-type]
        poll_seconds=0.05,
    )
    assert not hasattr(service, "_promotion")
    assert not hasattr(service, "_maybe_promote")
    worker = asyncio.create_task(service.run_worker())
    assert await service.enqueue(thread_id="t-m3", task_id="task-m3", user_id="user-m3")
    await asyncio.sleep(0.2)
    await service.stop()
    await worker
    from palatium_ai.domain.memory.namespaces import user_namespace

    hits = await port.search(namespace=user_namespace("user-m3"), query="tables", limit=4)
    assert hits
