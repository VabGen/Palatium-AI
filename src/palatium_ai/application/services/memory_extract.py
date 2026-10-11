# src/palatium_ai/application/services/memory_extract.py

"""Sleep-time memory **extract** queue: transcript → medium-term (060).

Axis (do not conflate with promote):
- extract = MemoryKeeper + ``save_memory`` → ``memory.entries`` (this service)
- promote = ``MemoryPromotionService`` / CronJob ``jobs.memory_promote`` → graph

MCP tool ``extract_transcript_memories`` enqueues this worker (070).
Durable queue: Postgres ``FOR UPDATE SKIP LOCKED`` (Wave M3); in-memory for tests.
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from palatium_ai.application.orchestration.agent_bridge import (
    memory_keeper_output_to_task_result,
    memory_keeper_to_agent_input,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.memory_keeper import MemoryKeeperInput
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace

if TYPE_CHECKING:
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.memory_keeper import MemoryKeeperAgent
    from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
    from palatium_ai.domain.memory.extract_queue import ExtractJobQueuePort
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort

logger = get_logger(__name__)

_DEFAULT_POLL_SECONDS = 0.5
_MAX_BACKOFF_SECONDS = 60.0
# Missing relation/column will not heal until a migration; stop instead of hot-looping.
_SCHEMA_FAILURES_TO_STOP = 5
_SCHEMA_ERROR_NAMES = frozenset(
    {
        "ProgrammingError",
        "UndefinedTableError",
        "UndefinedColumnError",
        "InvalidSchemaNameError",
    }
)


def _exception_chain(exc: BaseException) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        current = current.__cause__ or current.__context__
    return tuple(chain)


def _is_programming_error(exc: BaseException) -> bool:
    """Schema/SQL errors (missing table) — retrying at 500ms will not create DDL."""
    return any(type(item).__name__ in _SCHEMA_ERROR_NAMES for item in _exception_chain(exc))


def _is_operational_error(exc: BaseException) -> bool:
    """Connectivity blips — backoff and keep the worker alive."""
    if _is_programming_error(exc):
        return False
    return any(type(item).__name__ == "OperationalError" for item in _exception_chain(exc))


@dataclass(frozen=True, slots=True)
class MemoryExtractJob:
    """Sleep-time extract payload (transcript → medium)."""

    thread_id: str
    task_id: str
    user_id: str | None = None
    org_id: str | None = None
    job_id: UUID | None = None


class MemoryExtractService:
    """Enqueue extract; worker claims durable jobs and runs MemoryKeeper (no promote)."""

    def __init__(
        self,
        *,
        harness: Harness,
        memory_keeper: MemoryKeeperAgent,
        memory_port: MemoryPort,
        memory_persistence: MemoryFactPersistenceService,
        job_queue: ExtractJobQueuePort,
        dialog_turn_store: DialogTurnStore | None = None,
        poll_seconds: float = _DEFAULT_POLL_SECONDS,
    ) -> None:
        self._harness = harness
        self._memory_keeper = memory_keeper
        self._memory_port = memory_port
        self._memory_persistence = memory_persistence
        self._job_queue = job_queue
        self._dialog_turn_store = dialog_turn_store
        self._poll_seconds: float = max(0.05, poll_seconds)
        self._stop = asyncio.Event()

    async def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> bool:
        """Idempotent durable enqueue; False when queue is at capacity."""
        accepted = await self._job_queue.enqueue(
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            org_id=org_id,
        )
        if not accepted:
            logger.warning(
                "memory_extract.queue_full",
                thread_id=thread_id,
                task_id=task_id,
            )
        await self._record_queue_metrics()
        return accepted

    async def run_worker(self) -> None:
        """Background loop: claim SKIP LOCKED jobs until stop()."""
        self._stop.clear()
        schema_failures = 0
        operational_failures = 0
        while not self._stop.is_set():
            try:
                record = await self._job_queue.claim()
                schema_failures = 0
                operational_failures = 0
                if record is None:
                    await self._record_queue_metrics()
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
                    except TimeoutError:
                        continue
                    break
                job = MemoryExtractJob(
                    thread_id=record.thread_id,
                    task_id=record.task_id,
                    user_id=record.user_id,
                    org_id=record.org_id,
                    job_id=record.id,
                )
                try:
                    await self._process_job(job)
                    await self._job_queue.complete(record.id)
                except Exception as exc:
                    logger.error(
                        "memory_extract.failed",
                        thread_id=job.thread_id,
                        task_id=job.task_id,
                        job_id=str(record.id),
                        error_type=type(exc).__name__,
                        error=str(exc),
                    )
                    await self._job_queue.fail(record.id, error=str(exc))
                await self._record_queue_metrics()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                delay = self._backoff_for_worker_error(
                    exc,
                    schema_failures=schema_failures,
                    operational_failures=operational_failures,
                )
                if _is_programming_error(exc):
                    schema_failures += 1
                    if schema_failures >= _SCHEMA_FAILURES_TO_STOP:
                        logger.critical(
                            "memory_extract.worker_stopped",
                            reason="schema_error",
                            error_type=type(exc).__name__,
                            error=str(exc),
                            consecutive=schema_failures,
                        )
                        return
                elif _is_operational_error(exc):
                    operational_failures += 1
                await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Signal worker to exit after the current claim cycle."""
        self._stop.set()

    def _backoff_for_worker_error(
        self,
        exc: BaseException,
        *,
        schema_failures: int,
        operational_failures: int,
    ) -> float:
        """Classify claim/loop failures: schema errors stop; connectivity backs off."""
        error_type = type(exc).__name__
        if _is_programming_error(exc):
            step = schema_failures + 1
            delay: float = min(_MAX_BACKOFF_SECONDS, self._poll_seconds * (2 ** (step - 1)))
            logger.error(
                "memory_extract.schema_error",
                error_type=error_type,
                error=str(exc),
                consecutive=step,
                backoff_seconds=delay,
            )
            return delay
        if _is_operational_error(exc):
            step = operational_failures + 1
            delay = min(_MAX_BACKOFF_SECONDS, max(1.0, self._poll_seconds * (2 ** (step - 1))))
            logger.error(
                "memory_extract.operational_error",
                error_type=error_type,
                error=str(exc),
                consecutive=step,
                backoff_seconds=delay,
            )
            return delay
        logger.error("memory_extract.worker_error", error_type=error_type, error=str(exc))
        return self._poll_seconds

    @traceable(name="memory_extract.process_job")
    async def _process_job(self, job: MemoryExtractJob) -> None:
        excerpt = await self._load_excerpt(thread_id=job.thread_id)
        if not excerpt.strip():
            return
        thread_ns = thread_namespace(job.thread_id)
        user_ns = user_namespace(job.user_id) if job.user_id else None
        org_ns = org_namespace(job.org_id) if job.org_id else None
        existing = await self._memory_port.search(namespace=thread_ns, query=excerpt[:500], limit=8)
        if user_ns is not None:
            existing.extend(await self._memory_port.search(namespace=user_ns, query=excerpt[:500], limit=4))
        if org_ns is not None:
            existing.extend(await self._memory_port.search(namespace=org_ns, query=excerpt[:500], limit=4))
        existing_texts = tuple(str(item.get("text", "")).strip() for item in existing if str(item.get("text", "")).strip())
        task_input = MemoryKeeperInput(
            task_id=job.task_id,
            thread_id=job.thread_id,
            transcript_excerpt=excerpt,
            existing_memory_texts=existing_texts,
        )
        agent_input = memory_keeper_to_agent_input(
            task_input,
            trace_id=f"extract-{job.task_id}",
            thread_id=job.thread_id,
        )
        agent_output = await self._harness.execute_with_guardrails(self._memory_keeper, agent_input)
        result = memory_keeper_output_to_task_result(
            agent_output,
            task_id=job.task_id,
            agent_role=self._memory_keeper.config.role,
        )
        if result.output is None or not result.output.facts:
            return
        stored = await self._memory_persistence.persist_facts(job=job, facts=result.output.facts)
        logger.info(
            "memory_extract.stored",
            thread_id=job.thread_id,
            task_id=job.task_id,
            user_id=job.user_id or "",
            org_id=job.org_id or "",
            facts=len(result.output.facts),
            stored=stored,
        )

    async def _load_excerpt(self, *, thread_id: str) -> str:
        if self._dialog_turn_store is None:
            return ""
        window = await self._dialog_turn_store.list_recent_turns(thread_id=thread_id, limit=8)
        body = window.as_prompt_block()[:12000]
        # SB2: attachment UUID refs + titles in extract (not full OCR) so L3 knows
        # which documents were discussed without dumping fences into medium.
        meta_lines = _attachment_meta_lines(window)
        if not meta_lines:
            return body
        meta = "\n".join(meta_lines)
        combined = f"{body}\n\n[attachment_refs]\n{meta}"
        return combined[:12000]

    async def _record_queue_metrics(self) -> None:
        try:
            stats = await self._job_queue.stats()
        except Exception as exc:
            logger.debug("memory_extract.stats_failed", error=str(exc))
            return
        agent_metrics.record_memory_extract_queue(
            depth=stats.depth,
            lag_seconds=stats.lag_seconds,
            dead=stats.dead,
        )


def _attachment_meta_lines(window: object) -> list[str]:
    from palatium_ai.domain.memory.turns import ATTACHMENT_IDS_PAYLOAD_KEY, parse_turn_attachment_ids

    turns = getattr(window, "turns", ()) or ()
    lines: list[str] = []
    for turn in turns:
        if getattr(turn, "role", None) != "user":
            continue
        ids = parse_turn_attachment_ids(getattr(turn, "payload", None))
        if not ids:
            continue
        title = ""
        payload = getattr(turn, "payload", None)
        if isinstance(payload, dict):
            raw_title = payload.get("attachment_titles") or payload.get("title")
            if isinstance(raw_title, str) and raw_title.strip():
                title = raw_title.strip()[:120]
            elif isinstance(raw_title, list):
                title = ", ".join(str(t).strip() for t in raw_title if str(t).strip())[:120]
        id_csv = ",".join(str(i) for i in ids)
        if title:
            lines.append(f"- ids={id_csv}; title={title}")
        else:
            lines.append(f"- ids={id_csv}; key={ATTACHMENT_IDS_PAYLOAD_KEY}")
    return lines[:8]
