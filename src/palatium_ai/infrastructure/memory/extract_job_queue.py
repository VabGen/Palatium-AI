# src/palatium_ai/infrastructure/memory/extract_job_queue.py

"""In-memory + Postgres SKIP LOCKED extract job queues (Wave M3)."""

from __future__ import annotations

import asyncio

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update

from palatium_ai.domain.memory.extract_queue import (
    DEFAULT_LEASE_SECONDS,
    DEFAULT_MAX_QUEUE,
    ExtractEnqueueResult,
    ExtractJobRecord,
    ExtractQueueCapacity,
    ExtractQueueStats,
)
from palatium_ai.infrastructure.database.models.memory_extract_job import MemoryExtractJobORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_DEFAULT_LEASE_SECONDS = DEFAULT_LEASE_SECONDS
_DEFAULT_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 5
# Written when a crashed worker never reached ``fail()``: the lease expired, attempts ran out.
_EXHAUSTED_LEASE_REASON = "lease expired before completion; attempts exhausted"
# Transaction-scoped advisory lock that serializes ``enqueue`` (capacity check + insert).
# Enqueue happens once per turn, so the extract hot path does not feel it; without it two
# concurrent enqueues both pass the capacity check and either overshoot max_queue or race
# into the unique constraint (M3 audit E6).
_ENQUEUE_LOCK_KEY = 4_121_008_311


class InMemoryExtractJobQueue:
    """Process-local queue with lease reclaim (unit tests / no Postgres)."""

    def __init__(
        self,
        *,
        max_queue: int = DEFAULT_MAX_QUEUE,
        max_queue_per_tenant: int | None = None,
        lease_seconds: float = _DEFAULT_LEASE_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._capacity = ExtractQueueCapacity.from_limits(
            max_queue=max_queue,
            max_queue_per_tenant=max_queue_per_tenant,
        )
        self._lease_seconds = max(0.1, lease_seconds)
        self._max_attempts = max(1, max_attempts)
        self._rows: dict[UUID, ExtractJobRecord] = {}
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> ExtractEnqueueResult:
        async with self._lock:
            for row in self._rows.values():
                if row.thread_id == thread_id and row.task_id == task_id:
                    if row.status == "dead":
                        self._rows[row.id] = row.model_copy(
                            update={
                                "status": "pending",
                                "attempts": 0,
                                "available_at": datetime.now(UTC),
                                "leased_until": None,
                                "last_error": None,
                            }
                        )
                        return "queued"
                    return "queued"
            live = [r for r in self._rows.values() if r.status in {"pending", "running"}]
            if len(live) >= self._capacity.max_queue:
                return "queue_full"
            owner_live = sum(1 for r in live if r.user_id == user_id)
            if owner_live >= self._capacity.max_queue_per_tenant:
                return "tenant_full"
            job_id = uuid4()
            now = datetime.now(UTC)
            self._rows[job_id] = ExtractJobRecord(
                id=job_id,
                thread_id=thread_id,
                task_id=task_id,
                user_id=user_id,
                org_id=org_id,
                status="pending",
                attempts=0,
                max_attempts=self._max_attempts,
                available_at=now,
                created_at=now,
            )
            return "queued"

    async def claim(self) -> ExtractJobRecord | None:
        async with self._lock:
            now = datetime.now(UTC)
            self._bury_exhausted_locked(now)
            candidates = [
                row
                for row in self._rows.values()
                if row.attempts < row.max_attempts
                and (
                    (row.status == "pending" and (row.available_at is None or row.available_at <= now))
                    or (row.status == "running" and row.leased_until is not None and row.leased_until < now)
                )
            ]
            if not candidates:
                return None
            candidates.sort(key=lambda r: r.created_at or now)
            row = candidates[0]
            claimed = row.model_copy(
                update={
                    "status": "running",
                    "attempts": row.attempts + 1,
                    "leased_until": now + timedelta(seconds=self._lease_seconds),
                    "available_at": now,
                }
            )
            self._rows[row.id] = claimed
            return claimed

    def _bury_exhausted_locked(self, now: datetime) -> None:
        """Close the crash-loop hole: a job that never reached ``fail()`` must still die.

        ``claim`` is the only place that sees an expired lease, so the transition to
        ``dead`` has to happen here; otherwise attempts grow unbounded and the DLQ
        gauge stays at zero exactly when a poison job loops (M3 audit E1).
        """
        for job_id, row in list(self._rows.items()):
            if row.status not in {"pending", "running"} or row.attempts < row.max_attempts:
                continue
            if row.status == "running" and (row.leased_until is None or row.leased_until >= now):
                continue
            self._rows[job_id] = row.model_copy(
                update={
                    "status": "dead",
                    "leased_until": None,
                    "last_error": row.last_error or _EXHAUSTED_LEASE_REASON,
                }
            )

    async def renew(self, job_id: UUID) -> bool:
        async with self._lock:
            now = datetime.now(UTC)
            row = self._rows.get(job_id)
            if row is None or row.status != "running":
                return False
            if row.leased_until is None or row.leased_until <= now:
                return False  # already reclaimable: another worker may own it now
            self._rows[job_id] = row.model_copy(update={"leased_until": now + timedelta(seconds=self._lease_seconds)})
            return True

    async def complete(self, job_id: UUID) -> None:
        async with self._lock:
            row = self._rows.get(job_id)
            if row is None:
                return
            self._rows[job_id] = row.model_copy(update={"status": "done", "leased_until": None, "last_error": None})

    async def fail(self, job_id: UUID, *, error: str) -> None:
        async with self._lock:
            row = self._rows.get(job_id)
            if row is None:
                return
            now = datetime.now(UTC)
            if row.attempts >= row.max_attempts:
                self._rows[job_id] = row.model_copy(update={"status": "dead", "leased_until": None, "last_error": error[:2000]})
                return
            delay = _BACKOFF_BASE_SECONDS * (2 ** max(0, row.attempts - 1))
            self._rows[job_id] = row.model_copy(
                update={
                    "status": "pending",
                    "leased_until": None,
                    "available_at": now + timedelta(seconds=delay),
                    "last_error": error[:2000],
                }
            )

    async def stats(self) -> ExtractQueueStats:
        async with self._lock:
            now = datetime.now(UTC)
            pending_times: list[datetime] = []
            depth = 0
            dead = 0
            for row in self._rows.values():
                if row.status == "dead":
                    dead += 1
                elif row.status == "pending":
                    depth += 1
                    if row.created_at is not None:
                        pending_times.append(row.created_at)
                elif row.status == "running":
                    depth += 1
            lag = 0.0
            if pending_times:
                lag = max(0.0, (now - min(pending_times)).total_seconds())
            return ExtractQueueStats(depth=depth, lag_seconds=lag, dead=dead)


class PostgresExtractJobQueue:
    """Durable extract queue: ``FOR UPDATE SKIP LOCKED`` claim."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        max_queue: int = DEFAULT_MAX_QUEUE,
        max_queue_per_tenant: int | None = None,
        lease_seconds: float = _DEFAULT_LEASE_SECONDS,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> None:
        self._session_factory = session_factory
        self._capacity = ExtractQueueCapacity.from_limits(
            max_queue=max_queue,
            max_queue_per_tenant=max_queue_per_tenant,
        )
        self._lease_seconds = max(0.1, lease_seconds)
        self._max_attempts = max(1, max_attempts)

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> ExtractEnqueueResult:
        """Idempotent enqueue under one transaction (advisory lock + ON CONFLICT; M3 E6/E7).

        Returns a refusal only for a *new* job: a duplicate ``(thread_id, task_id)`` is
        ``queued`` (it is already there) and a ``dead`` job is revived, exactly like the
        in-memory implementation. Two ceilings are checked in the insert itself, so a
        concurrent enqueue cannot pass them: the global backlog and this owner's share.
        """
        now = datetime.now(UTC)
        scope = {"thread_id": thread_id, "task_id": task_id, "user_id": user_id, "org_id": org_id}
        async with self._session_factory() as session:
            await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _ENQUEUE_LOCK_KEY})
            revived = await session.execute(
                text(
                    """
                    UPDATE memory.extract_jobs
                    SET status = 'pending',
                        attempts = 0,
                        available_at = :now,
                        leased_until = NULL,
                        last_error = NULL,
                        user_id = :user_id,
                        org_id = :org_id,
                        updated_at = :now
                    WHERE thread_id = :thread_id AND task_id = :task_id AND status = 'dead'
                    RETURNING id
                    """
                ),
                {**scope, "now": now},
            )
            if revived.first() is not None:
                await session.commit()
                return "queued"
            inserted = await session.execute(
                text(
                    """
                    INSERT INTO memory.extract_jobs
                        (id, thread_id, task_id, user_id, org_id, status, attempts,
                         max_attempts, available_at)
                    SELECT :id, :thread_id, :task_id, :user_id, :org_id, 'pending', 0,
                           :max_attempts, :now
                    FROM (
                        SELECT
                            count(*) FILTER (WHERE status IN ('pending', 'running')) AS total,
                            count(*) FILTER (
                                WHERE status IN ('pending', 'running')
                                  AND user_id IS NOT DISTINCT FROM :user_id
                            ) AS owner_total
                        FROM memory.extract_jobs
                    ) AS live
                    WHERE live.total < :max_queue
                      AND live.owner_total < :max_queue_per_tenant
                    ON CONFLICT (thread_id, task_id) DO NOTHING
                    RETURNING id
                    """
                ),
                {
                    **scope,
                    "id": uuid4(),
                    "max_attempts": self._max_attempts,
                    "max_queue": self._capacity.max_queue,
                    "max_queue_per_tenant": self._capacity.max_queue_per_tenant,
                    "now": now,
                },
            )
            if inserted.first() is not None:
                await session.commit()
                return "queued"
            # Nothing inserted: the task is already queued (accepted) or a ceiling refused it.
            existing = await session.scalar(
                select(MemoryExtractJobORM.id).where(
                    MemoryExtractJobORM.thread_id == thread_id,
                    MemoryExtractJobORM.task_id == task_id,
                )
            )
            if existing is not None:
                await session.commit()
                return "queued"
            refusal = await self._refusal_reason(session, user_id=user_id)
            await session.commit()
            return refusal

    async def _refusal_reason(self, session: AsyncSession, *, user_id: str | None) -> ExtractEnqueueResult:
        """Which ceiling blocked the insert — the counts are stable under the enqueue lock."""
        counts = (
            await session.execute(
                text(
                    """
                    SELECT
                        count(*) FILTER (WHERE status IN ('pending', 'running')) AS total,
                        count(*) FILTER (
                            WHERE status IN ('pending', 'running')
                              AND user_id IS NOT DISTINCT FROM :user_id
                        ) AS owner_total
                    FROM memory.extract_jobs
                    """
                ),
                {"user_id": user_id},
            )
        ).one()
        if int(counts.total or 0) >= self._capacity.max_queue:
            return "queue_full"
        return "tenant_full"

    async def claim(self) -> ExtractJobRecord | None:
        now = datetime.now(UTC)
        lease_until = now + timedelta(seconds=self._lease_seconds)
        async with self._session_factory() as session:
            await self._bury_exhausted_leases(session, now=now)
            result = await session.execute(
                text(
                    """
                    UPDATE memory.extract_jobs AS j
                    SET status = 'running',
                        attempts = j.attempts + 1,
                        leased_until = :lease_until,
                        available_at = :now,
                        updated_at = :now
                    WHERE j.id = (
                        SELECT id
                        FROM memory.extract_jobs
                        WHERE attempts < max_attempts AND (
                            (status = 'pending' AND available_at <= :now) OR
                            (status = 'running' AND leased_until IS NOT NULL AND leased_until < :now)
                        )
                        ORDER BY created_at ASC
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    RETURNING
                        id, thread_id, task_id, user_id, org_id, status, attempts,
                        max_attempts, available_at, leased_until, last_error, created_at
                    """
                ),
                {"now": now, "lease_until": lease_until},
            )
            row = result.mappings().first()
            await session.commit()
        if row is None:
            return None
        return ExtractJobRecord(
            id=row["id"],
            thread_id=row["thread_id"],
            task_id=row["task_id"],
            user_id=row["user_id"],
            org_id=row["org_id"],
            status="running",
            attempts=int(row["attempts"] or 0),
            max_attempts=int(row["max_attempts"] or self._max_attempts),
            available_at=row["available_at"],
            leased_until=row["leased_until"],
            last_error=row["last_error"],
            created_at=row["created_at"],
        )

    async def _bury_exhausted_leases(self, session: AsyncSession, *, now: datetime) -> None:
        """Move crashed, attempt-exhausted jobs to the DLQ before claiming (M3 audit E1).

        ``fail()`` only runs when the worker survives long enough to catch the error; a
        killed process leaves ``running`` rows that would otherwise be reclaimed forever.
        """
        await session.execute(
            text(
                """
                UPDATE memory.extract_jobs
                SET status = 'dead',
                    leased_until = NULL,
                    updated_at = :now,
                    last_error = COALESCE(last_error, :reason)
                WHERE status IN ('pending', 'running')
                  AND attempts >= max_attempts
                  AND (
                      status = 'pending'
                      OR leased_until IS NULL
                      OR leased_until < :now
                  )
                """
            ),
            {"now": now, "reason": _EXHAUSTED_LEASE_REASON},
        )

    async def renew(self, job_id: UUID) -> bool:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    UPDATE memory.extract_jobs
                    SET leased_until = :until, updated_at = :now
                    WHERE id = :job_id
                      AND status = 'running'
                      AND leased_until IS NOT NULL
                      AND leased_until > :now
                    RETURNING id
                    """
                ),
                {
                    "job_id": job_id,
                    "until": now + timedelta(seconds=self._lease_seconds),
                    "now": now,
                },
            )
            renewed = result.first() is not None
            await session.commit()
        return renewed

    async def complete(self, job_id: UUID) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            await session.execute(
                update(MemoryExtractJobORM)
                .where(MemoryExtractJobORM.id == job_id)
                .values(status="done", leased_until=None, last_error=None, updated_at=now)
            )
            await session.commit()

    async def fail(self, job_id: UUID, *, error: str) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            row = await session.get(MemoryExtractJobORM, job_id)
            if row is None:
                return
            if row.attempts >= row.max_attempts:
                row.status = "dead"
                row.leased_until = None
                row.last_error = error[:2000]
                row.updated_at = now
            else:
                delay = _BACKOFF_BASE_SECONDS * (2 ** max(0, row.attempts - 1))
                row.status = "pending"
                row.leased_until = None
                row.available_at = now + timedelta(seconds=delay)
                row.last_error = error[:2000]
                row.updated_at = now
            await session.commit()

    async def stats(self) -> ExtractQueueStats:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            depth = await session.scalar(
                select(func.count())
                .select_from(MemoryExtractJobORM)
                .where(MemoryExtractJobORM.status.in_(("pending", "running")))
            )
            dead = await session.scalar(
                select(func.count()).select_from(MemoryExtractJobORM).where(MemoryExtractJobORM.status == "dead")
            )
            oldest = await session.scalar(
                select(func.min(MemoryExtractJobORM.created_at)).where(MemoryExtractJobORM.status == "pending")
            )
        lag = 0.0
        if oldest is not None:
            aware = oldest if oldest.tzinfo is not None else oldest.replace(tzinfo=UTC)
            lag = max(0.0, (now - aware).total_seconds())
        return ExtractQueueStats(depth=int(depth or 0), lag_seconds=lag, dead=int(dead or 0))
