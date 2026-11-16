# src/palatium_ai/domain/memory/extract_queue.py

"""Durable sleep-time extract job queue contract (Wave M3 / SKIP LOCKED)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from palatium_ai.core.types.extract_queue import (
    DEFAULT_MAX_QUEUE,
    MIN_TENANT_SLOTS,
    fair_share_queue_cap,
)

__all__ = [
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_MAX_QUEUE",
    "MIN_TENANT_SLOTS",
    "ExtractEnqueueResult",
    "ExtractJobQueuePort",
    "ExtractJobRecord",
    "ExtractJobStatus",
    "ExtractLeaseLostError",
    "ExtractQueueCapacity",
    "ExtractQueueStats",
    "fair_share_queue_cap",
    "is_queued",
]

ExtractJobStatus = Literal["pending", "running", "done", "dead"]

#: Outcome of an enqueue attempt. A plain bool lost the distinction between "the whole
#: queue is full" and "this owner used up its share", which is the only thing an operator
#: can act on (M3 audit E7) — so the refusal reason is part of the contract.
ExtractEnqueueResult = Literal["queued", "queue_full", "tenant_full"]

#: Lease granted to a claimed job and renewed while it runs (single source for queue + worker).
DEFAULT_LEASE_SECONDS = 300.0

# Numeric admission defaults (``DEFAULT_MAX_QUEUE`` / ``MIN_TENANT_SLOTS`` /
# ``fair_share_queue_cap``) are re-exported from ``core/types/extract_queue.py`` above:
# settings and domain need the same numbers, and ``core`` must not import ``domain``.


def is_queued(result: ExtractEnqueueResult) -> bool:
    """Explicit predicate — a Literal result is always truthy, so ``if result`` would lie."""
    return result == "queued"


class ExtractQueueCapacity(BaseModel, frozen=True):
    """Admission limits for the durable extract queue (global + per owner).

    Both are ceilings on ``pending + running`` rows. The per-owner cap exists so that one
    owner cannot fill the shared backlog and turn every other owner's extract into
    ``tenant_full`` (M3 audit E7). Enforced inside the same transaction/lock as the insert,
    so the check cannot race with a concurrent enqueue (M3 E6).
    """

    max_queue: int = Field(default=DEFAULT_MAX_QUEUE, ge=1, le=100_000)
    max_queue_per_tenant: int = Field(default=fair_share_queue_cap(DEFAULT_MAX_QUEUE), ge=1, le=100_000)

    @model_validator(mode="after")
    def _per_tenant_within_global(self) -> ExtractQueueCapacity:
        if self.max_queue_per_tenant > self.max_queue:
            msg = (
                "max_queue_per_tenant must not exceed max_queue: a per-owner cap above the "
                "global ceiling is the global ceiling (misconfig fails closed)"
            )
            raise ValueError(msg)
        return self

    @classmethod
    def from_limits(cls, *, max_queue: int, max_queue_per_tenant: int | None = None) -> ExtractQueueCapacity:
        """Build from constructor-style limits; ``None`` derives the fair share."""
        return cls(
            max_queue=max_queue,
            max_queue_per_tenant=fair_share_queue_cap(max_queue) if max_queue_per_tenant is None else max_queue_per_tenant,
        )


class ExtractLeaseLostError(RuntimeError):
    """The worker no longer owns the job lease; another worker may be processing it (M3 E2)."""


class ExtractJobRecord(BaseModel, frozen=True):
    """One claimable / claimed extract job row."""

    id: UUID
    thread_id: str
    task_id: str
    user_id: str | None = None
    org_id: str | None = None
    status: ExtractJobStatus = "pending"
    attempts: int = Field(default=0, ge=0)
    max_attempts: int = Field(default=3, ge=1)
    available_at: datetime | None = None
    leased_until: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None


class ExtractQueueStats(BaseModel, frozen=True):
    """Depth (pending+running reclaimable) and oldest pending lag seconds."""

    depth: int = Field(ge=0)
    lag_seconds: float = Field(ge=0.0)
    dead: int = Field(default=0, ge=0)


class ExtractJobQueuePort(Protocol):
    """Enqueue / claim / complete extract jobs (Postgres SKIP LOCKED in prod)."""

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> ExtractEnqueueResult:
        """Idempotent enqueue; ``queued`` unless a capacity ceiling refuses it.

        ``queue_full`` = the global backlog ceiling; ``tenant_full`` = this owner's share.
        A duplicate ``(thread_id, task_id)`` is always ``queued`` (it already exists).
        """
        ...

    async def claim(self) -> ExtractJobRecord | None:
        """Claim next available job (FOR UPDATE SKIP LOCKED); None if idle.

        Claim is also the DLQ boundary: an expired lease whose ``attempts`` reached
        ``max_attempts`` is moved to ``dead`` instead of being redelivered.
        """
        ...

    async def renew(self, job_id: UUID) -> bool:
        """Extend the lease of a running job; ``False`` when this worker lost ownership.

        A worker renews while the job executes and aborts as soon as the queue answers
        ``False`` — the row is expired, reclaimed or already finished (M3 E2).
        """
        ...

    async def complete(self, job_id: UUID) -> None:
        """Mark job done (idempotent)."""
        ...

    async def fail(self, job_id: UUID, *, error: str) -> None:
        """Retry with backoff or move to dead-letter when attempts exhausted."""
        ...

    async def stats(self) -> ExtractQueueStats:
        """Queue depth / lag for metrics."""
        ...
