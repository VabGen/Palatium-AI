# src/palatium_ai/domain/memory/extract_queue.py

"""Durable sleep-time extract job queue contract (Wave M3 / SKIP LOCKED)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field

ExtractJobStatus = Literal["pending", "running", "done", "dead"]


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
    ) -> bool:
        """Idempotent enqueue; False when queue at capacity (drop)."""
        ...

    async def claim(self) -> ExtractJobRecord | None:
        """Claim next available job (FOR UPDATE SKIP LOCKED); None if idle."""
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
