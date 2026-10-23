# tests/unit/test_memory_extract_queue.py

"""Durable extract queue + axis split (Wave M3)."""

from __future__ import annotations

import asyncio
import json

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from pydantic import ValidationError

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from palatium_ai.application.services.memory_extract import MemoryExtractJob, MemoryExtractService
from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
from palatium_ai.core.config.memory import MemoryConfig
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.memory.extract_queue import (
    DEFAULT_MAX_QUEUE,
    MIN_TENANT_SLOTS,
    ExtractJobRecord,
    ExtractLeaseLostError,
    ExtractQueueCapacity,
    ExtractQueueStats,
    fair_share_queue_cap,
    is_queued,
)
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow
from palatium_ai.infrastructure.mcp.memory_tool_ops import extract_transcript_memories
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
    assert await queue.enqueue(thread_id="t1", task_id="job-1", user_id="u1") == "queued"
    assert await queue.enqueue(thread_id="t1", task_id="job-1", user_id="u1") == "queued"
    stats = await queue.stats()
    assert stats.depth == 1


@pytest.mark.asyncio()
async def test_queue_full_rejects() -> None:
    queue = InMemoryExtractJobQueue(max_queue=1)
    assert await queue.enqueue(thread_id="t1", task_id="a") == "queued"
    assert await queue.enqueue(thread_id="t1", task_id="b") == "queue_full"


def test_capacity_derives_the_fair_share_and_rejects_a_cap_above_the_global_one() -> None:
    """E7 config contract: the per-owner cap is derived, and a nonsense one fails closed."""
    capacity = ExtractQueueCapacity.from_limits(max_queue=DEFAULT_MAX_QUEUE)
    assert capacity.max_queue == DEFAULT_MAX_QUEUE
    assert capacity.max_queue_per_tenant == fair_share_queue_cap(DEFAULT_MAX_QUEUE) == DEFAULT_MAX_QUEUE // MIN_TENANT_SLOTS
    # Explicit value wins; a cap above the global ceiling is the global ceiling — reject it.
    assert ExtractQueueCapacity.from_limits(max_queue=8, max_queue_per_tenant=3).max_queue_per_tenant == 3
    with pytest.raises(ValueError, match="must not exceed max_queue"):
        ExtractQueueCapacity(max_queue=4, max_queue_per_tenant=5)


def test_settings_derive_the_fair_share_and_reject_a_cap_above_the_global_one() -> None:
    """E7 at the settings boundary: the env default is complete, a bad pairing fails closed."""
    config = MemoryConfig()
    assert config.extract_queue_limits == (DEFAULT_MAX_QUEUE, fair_share_queue_cap(DEFAULT_MAX_QUEUE))
    assert MemoryConfig(extract_max_queue=8, extract_max_queue_per_tenant=3).extract_queue_limits == (8, 3)
    with pytest.raises(ValidationError, match="must not exceed"):
        MemoryConfig(extract_max_queue=4, extract_max_queue_per_tenant=5)


def test_is_queued_is_not_truthiness() -> None:
    """A refusal is a non-empty Literal, so ``if result`` would treat it as success."""
    assert is_queued("queued")
    assert not is_queued("queue_full")
    assert not is_queued("tenant_full")
    assert bool("tenant_full") is True  # the trap the predicate exists for


@pytest.mark.asyncio()
async def test_tenant_share_is_refused_before_the_global_ceiling() -> None:
    """E7: one noisy owner must not fill the shared backlog.

    ``max_queue=8`` gives the owner a fair share of 2 (``max_queue // MIN_TENANT_SLOTS``).
    The third job is refused while half the backlog is still free — and another owner is
    admitted, which is the whole point: the refusal is attributable, not global.
    """
    queue = InMemoryExtractJobQueue(max_queue=8)
    assert await queue.enqueue(thread_id="noisy", task_id="a", user_id="noisy") == "queued"
    assert await queue.enqueue(thread_id="noisy", task_id="b", user_id="noisy") == "queued"

    assert await queue.enqueue(thread_id="noisy", task_id="c", user_id="noisy") == "tenant_full"
    # Capacity is still there for everyone else, and the global ceiling is untouched.
    assert await queue.enqueue(thread_id="quiet", task_id="d", user_id="quiet") == "queued"
    assert (await queue.stats()).depth == 3
    # A duplicate of an already queued job is idempotent, not a capacity refusal.
    assert await queue.enqueue(thread_id="noisy", task_id="a", user_id="noisy") == "queued"


@pytest.mark.asyncio()
async def test_lease_expiry_allows_redelivery_without_dup_row() -> None:
    queue = InMemoryExtractJobQueue(max_queue=8, lease_seconds=1, max_attempts=3)
    assert await queue.enqueue(thread_id="t1", task_id="reclaim-1", user_id="u1") == "queued"
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
async def test_expired_lease_with_exhausted_attempts_moves_to_dead_letter() -> None:
    """Crash-loop regression (M3 audit E1): kill -9 never reaches ``fail()``."""
    queue = InMemoryExtractJobQueue(max_queue=8, lease_seconds=1, max_attempts=2)
    assert await queue.enqueue(thread_id="t1", task_id="crash-1") == "queued"
    first = await queue.claim()
    assert first is not None
    # Worker died after the final allowed attempt: attempts == max_attempts, lease expired.
    crashed = first.model_copy(
        update={
            "attempts": first.max_attempts,
            "leased_until": datetime.now(UTC) - timedelta(seconds=1),
        }
    )
    queue._rows[first.id] = crashed

    assert await queue.claim() is None

    stats = await queue.stats()
    assert stats.dead == 1
    assert queue._rows[first.id].status == "dead"


@pytest.mark.asyncio()
async def test_expired_lease_below_max_attempts_is_still_reclaimed() -> None:
    """The DLQ guard must not swallow redelivery that is still within budget."""
    queue = InMemoryExtractJobQueue(max_queue=8, lease_seconds=1, max_attempts=3)
    assert await queue.enqueue(thread_id="t1", task_id="retry-ok") == "queued"
    first = await queue.claim()
    assert first is not None
    queue._rows[first.id] = first.model_copy(update={"leased_until": datetime.now(UTC) - timedelta(seconds=1)})

    second = await queue.claim()
    assert second is not None
    assert second.id == first.id
    assert second.attempts == 2
    assert (await queue.stats()).dead == 0


@pytest.mark.asyncio()
async def test_fail_moves_to_dead_letter() -> None:
    queue = InMemoryExtractJobQueue(max_queue=8, max_attempts=2)
    await queue.enqueue(thread_id="t1", task_id="dead-1")
    job = await queue.claim()
    assert job is not None
    await queue.fail(job.id, error="boom1")
    # Backoff: force available for second attempt.
    pending = queue._rows[job.id]
    queue._rows[job.id] = pending.model_copy(update={"available_at": datetime.now(UTC) - timedelta(seconds=1)})
    job2 = await queue.claim()
    assert job2 is not None
    await queue.fail(job2.id, error="boom2")
    stats = await queue.stats()
    assert stats.dead == 1
    assert await queue.claim() is None


class _ResultingConsolidation:
    """Minimal stand-in that answers with a chosen enqueue outcome."""

    def __init__(self, result: str) -> None:
        self.result = result

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> str:
        _ = (thread_id, task_id, user_id, org_id)
        return self.result


@pytest.mark.asyncio()
@pytest.mark.parametrize(
    "result,is_error",
    (
        ("queued", False),
        ("queue_full", True),
        ("tenant_full", True),
    ),
)
async def test_mcp_extract_payload_names_the_refusal_reason(result: str, is_error: bool) -> None:
    """The tool contract must not collapse "my share" into "the queue" (M3 E7)."""
    response = await extract_transcript_memories(
        _ResultingConsolidation(result),  # type: ignore[arg-type]
        {"user_id": "u1", "thread_id": "t1"},
    )
    payload = json.loads(response.content[0]["text"])
    assert payload["status"] == result
    assert response.is_error is is_error


@pytest.mark.asyncio()
async def test_service_counts_and_logs_a_refusal_with_its_reason() -> None:
    """A refusal is only actionable when it is counted by ceiling, not as a bare warning."""
    queue = InMemoryExtractJobQueue(max_queue=8)
    service = MemoryExtractService(
        harness=AsyncMock(),
        memory_keeper=AsyncMock(),
        memory_port=InMemoryMemoryPort(),
        memory_persistence=AsyncMock(),
        job_queue=queue,
    )
    before = agent_metrics.memory_extract_enqueue_refused_count("tenant_full")
    for task in ("a", "b"):
        assert await service.enqueue(thread_id="t", task_id=task, user_id="noisy") == "queued"
    assert await service.enqueue(thread_id="t", task_id="c", user_id="noisy") == "tenant_full"
    assert agent_metrics.memory_extract_enqueue_refused_count("tenant_full") == before + 1


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
    assert await service.enqueue(thread_id="t-m3", task_id="task-m3", user_id="user-m3") == "queued"
    await asyncio.sleep(0.2)
    await service.stop()
    await worker
    from palatium_ai.domain.memory.namespaces import user_namespace

    hits = await port.search(namespace=user_namespace("user-m3"), query="tables", limit=4)
    assert hits


class _MissingExtractJobsQueue:
    """Claim always fails as if ``memory.extract_jobs`` was never migrated."""

    def __init__(self) -> None:
        self.calls = 0

    async def claim(self) -> None:
        self.calls += 1
        from sqlalchemy.exc import ProgrammingError

        raise ProgrammingError(
            "UPDATE memory.extract_jobs",
            {},
            Exception('relation "memory.extract_jobs" does not exist'),
        )


@pytest.mark.asyncio()
async def test_extract_worker_stops_on_missing_table() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from palatium_ai.application.services.memory_extract import _SCHEMA_FAILURES_TO_STOP

    queue = _MissingExtractJobsQueue()
    service = MemoryExtractService(
        harness=MagicMock(),
        memory_keeper=MagicMock(),
        memory_port=MagicMock(),
        memory_persistence=MagicMock(),
        job_queue=queue,  # type: ignore[arg-type]
        poll_seconds=0.5,
    )
    sleep = AsyncMock()
    with patch("palatium_ai.application.services.memory_extract.asyncio.sleep", sleep):
        await service.run_worker()
    assert queue.calls == _SCHEMA_FAILURES_TO_STOP
    assert sleep.await_count == _SCHEMA_FAILURES_TO_STOP - 1
    delays = [call.args[0] for call in sleep.await_args_list]
    assert delays == [0.5, 1.0, 2.0, 4.0]


class _LeaseStubQueue:
    """Hands out one job, then idle; records whether the lease was renewed/lost (M3 E2)."""

    def __init__(self, *, renew_after: int) -> None:
        self._renew_after = renew_after
        self.renew_calls = 0
        self.completed: list[object] = []
        self.failed: list[object] = []
        self._claimed = False
        self._job = ExtractJobRecord(
            id=uuid4(),
            thread_id="t-lease",
            task_id="task-lease",
            status="running",
            attempts=1,
            max_attempts=3,
        )

    async def claim(self) -> ExtractJobRecord | None:
        if self._claimed:
            return None
        self._claimed = True
        return self._job

    async def renew(self, job_id: object) -> bool:
        self.renew_calls += 1
        return self.renew_calls <= self._renew_after

    async def complete(self, job_id: object) -> None:
        self.completed.append(job_id)

    async def fail(self, job_id: object, *, error: str) -> None:
        self.failed.append((job_id, error))

    async def stats(self) -> ExtractQueueStats:
        return ExtractQueueStats(depth=0, lag_seconds=0.0)


def _lease_service(queue: _LeaseStubQueue, *, lease_seconds: float) -> MemoryExtractService:
    from unittest.mock import MagicMock

    return MemoryExtractService(
        harness=MagicMock(),
        memory_keeper=MagicMock(),
        memory_port=MagicMock(),
        memory_persistence=MagicMock(),
        job_queue=queue,  # type: ignore[arg-type]
        lease_seconds=lease_seconds,
        poll_seconds=0.02,
    )


@pytest.mark.asyncio()
async def test_worker_renews_lease_while_job_runs() -> None:
    """E2: a job longer than the lease must not be cancelled while renewals succeed."""
    queue = _LeaseStubQueue(renew_after=100)
    service = _lease_service(queue, lease_seconds=0.15)
    processed = asyncio.Event()

    async def _slow_job(_job: object) -> None:
        await asyncio.sleep(0.2)  # outlives one 0.15 s lease
        processed.set()

    service._process_job = _slow_job  # type: ignore[method-assign]
    worker = asyncio.create_task(service.run_worker())
    await asyncio.wait_for(processed.wait(), timeout=2.0)
    await service.stop()
    await asyncio.wait_for(worker, timeout=2.0)

    assert queue.renew_calls >= 2
    assert queue.completed
    assert queue.failed == []


@pytest.mark.asyncio()
async def test_worker_aborts_job_when_lease_is_lost() -> None:
    """E2: once renew() says the row is not ours, continuing means a double write."""
    queue = _LeaseStubQueue(renew_after=0)
    service = _lease_service(queue, lease_seconds=0.15)
    cancelled = asyncio.Event()

    async def _hanging_job(_job: object) -> None:
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    service._process_job = _hanging_job  # type: ignore[method-assign]
    worker = asyncio.create_task(service.run_worker())
    await asyncio.wait_for(cancelled.wait(), timeout=2.0)
    await service.stop()
    await asyncio.wait_for(worker, timeout=2.0)

    assert queue.renew_calls >= 1
    assert queue.completed == []
    # A lost lease is not a job failure: fail() would reschedule a row owned by another worker.
    assert queue.failed == []


@pytest.mark.asyncio()
async def test_renew_extends_live_lease() -> None:
    queue = InMemoryExtractJobQueue(max_queue=4, lease_seconds=0.2)
    assert await queue.enqueue(thread_id="t1", task_id="renew-1") == "queued"
    job = await queue.claim()
    assert job is not None
    before = queue._rows[job.id].leased_until
    assert await queue.renew(job.id) is True
    after = queue._rows[job.id].leased_until
    assert before is not None
    assert after is not None
    assert after > before


@pytest.mark.asyncio()
async def test_renew_refuses_expired_or_finished_lease() -> None:
    queue = InMemoryExtractJobQueue(max_queue=4, lease_seconds=0.2)
    assert await queue.enqueue(thread_id="t1", task_id="renew-2") == "queued"
    job = await queue.claim()
    assert job is not None

    expired = queue._rows[job.id].model_copy(update={"leased_until": datetime.now(UTC) - timedelta(seconds=1)})
    queue._rows[job.id] = expired
    assert await queue.renew(job.id) is False

    queue._rows[job.id] = expired.model_copy(update={"status": "done"})
    assert await queue.renew(job.id) is False


@pytest.mark.asyncio()
async def test_worker_does_not_abort_job_when_heartbeat_is_slow() -> None:
    """Guard against a heartbeat design that starves the job task on a fast lease."""
    queue = _LeaseStubQueue(renew_after=100)
    service = _lease_service(queue, lease_seconds=0.3)
    processed = asyncio.Event()

    async def _quick_job(_job: object) -> None:
        processed.set()

    service._process_job = _quick_job  # type: ignore[method-assign]
    worker = asyncio.create_task(service.run_worker())
    await asyncio.wait_for(processed.wait(), timeout=2.0)
    await service.stop()
    await asyncio.wait_for(worker, timeout=2.0)
    assert queue.completed


_FACT_PAYLOAD = {
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


class _OwnershipStubQueue:
    """Queue whose only interesting answer is ``renew`` — the write-path ownership probe."""

    def __init__(self, *, owned: bool) -> None:
        self._owned = owned
        self.renew_calls = 0

    async def renew(self, job_id: object) -> bool:
        self.renew_calls += 1
        return self._owned


def _write_path_service(queue: _OwnershipStubQueue) -> tuple[MemoryExtractService, AsyncMock]:
    from unittest.mock import MagicMock

    port = InMemoryMemoryPort()
    harness = Harness(llm=FakeLLMPort(json.dumps(_FACT_PAYLOAD)))
    persistence = MagicMock()
    persistence.persist_facts = AsyncMock(return_value=1)
    service = MemoryExtractService(
        harness=harness,
        memory_keeper=MemoryKeeperAgent(harness, MEMORY_KEEPER_CONFIG),
        memory_port=port,
        memory_persistence=persistence,
        job_queue=queue,  # type: ignore[arg-type]
        dialog_turn_store=_FakeDialog(),  # type: ignore[arg-type]
    )
    return service, persistence.persist_facts


@pytest.mark.asyncio()
async def test_write_path_refuses_facts_after_lease_loss() -> None:
    """E2b: after a stall past the lease the row belongs to another worker — write nothing.

    The heartbeat alone cannot cover this: a frozen event loop freezes it too, and on
    resume the job continuation may run first. The probe sits *inside* the job, right
    before the writes, so ownership is checked at the moment it matters.
    """
    queue = _OwnershipStubQueue(owned=False)
    service, persist = _write_path_service(queue)
    job = MemoryExtractJob(thread_id="t-e2b", task_id="task-e2b", user_id="user-e2b", job_id=uuid4())

    with pytest.raises(ExtractLeaseLostError):
        await service._process_job(job)

    assert queue.renew_calls == 1
    persist.assert_not_awaited()


@pytest.mark.asyncio()
async def test_write_path_reserves_the_lease_before_persisting() -> None:
    """A granted probe extends the lease, which is what makes the write window safe."""
    queue = _OwnershipStubQueue(owned=True)
    service, persist = _write_path_service(queue)
    job = MemoryExtractJob(thread_id="t-e2b", task_id="task-e2b", user_id="user-e2b", job_id=uuid4())

    await service._process_job(job)

    assert queue.renew_calls == 1
    persist.assert_awaited_once()


@pytest.mark.asyncio()
async def test_write_path_skips_the_probe_without_a_durable_job() -> None:
    """A job with no ``job_id`` has no lease to check — the in-process caller is the writer."""
    queue = _OwnershipStubQueue(owned=False)
    service, persist = _write_path_service(queue)
    job = MemoryExtractJob(thread_id="t-e2b", task_id="task-e2b", user_id="user-e2b")

    await service._process_job(job)

    assert queue.renew_calls == 0
    persist.assert_awaited_once()
