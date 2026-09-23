# src/palatium_ai/application/services/memory_extract.py

"""Sleep-time memory **extract** queue: transcript → medium-term (060).

Axis (do not conflate with promote):
- extract = MemoryKeeper + ``save_memory`` → ``memory.entries``
- promote = ``MemoryPromotionService`` / ``PromotionPolicy`` → graph (medium→long)

MCP tool ``consolidate_memory`` is a legacy name for *enqueue extract*
(070 closed list; rename to ``extract_transcript_memories`` needs separate discussion).
"""

from __future__ import annotations

import asyncio

from dataclasses import dataclass
from typing import TYPE_CHECKING

from palatium_ai.application.orchestration.agent_bridge import (
    memory_keeper_output_to_task_result,
    memory_keeper_to_agent_input,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.memory_keeper import MemoryKeeperInput
from palatium_ai.domain.memory.namespaces import org_namespace, thread_namespace, user_namespace

if TYPE_CHECKING:
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.memory_keeper import MemoryKeeperAgent
    from palatium_ai.application.services.memory_fact_persistence import MemoryFactPersistenceService
    from palatium_ai.application.services.memory_promotion import MemoryPromotionService
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class MemoryExtractJob:
    """Queued sleep-time extract after a successful process turn."""

    thread_id: str
    task_id: str
    user_id: str | None = None
    org_id: str | None = None


class MemoryExtractService:
    """Enqueue extract; worker runs MemoryKeeper off the request path, then optional promote."""

    def __init__(
        self,
        *,
        harness: Harness,
        memory_keeper: MemoryKeeperAgent,
        memory_port: MemoryPort,
        memory_persistence: MemoryFactPersistenceService,
        dialog_turn_store: DialogTurnStore | None = None,
        promotion: MemoryPromotionService | None = None,
        promote_batch_limit: int = 32,
        max_queue: int = 256,
    ) -> None:
        self._harness = harness
        self._memory_keeper = memory_keeper
        self._memory_port = memory_port
        self._memory_persistence = memory_persistence
        self._dialog_turn_store = dialog_turn_store
        self._promotion = promotion
        self._promote_batch_limit = max(1, min(promote_batch_limit, 128))
        self._queue: asyncio.Queue[MemoryExtractJob | None] = asyncio.Queue(maxsize=max_queue)

    def enqueue(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> bool:
        """Non-blocking enqueue; returns False if queue is full (drop + log)."""
        job = MemoryExtractJob(thread_id=thread_id, task_id=task_id, user_id=user_id, org_id=org_id)
        try:
            self._queue.put_nowait(job)
            return True
        except asyncio.QueueFull:
            logger.warning(
                "memory_extract.queue_full",
                thread_id=thread_id,
                task_id=task_id,
            )
            return False

    async def run_worker(self) -> None:
        """Background loop: process jobs until sentinel None is received."""
        while True:
            job = await self._queue.get()
            try:
                if job is None:
                    return
                await self._process_job(job)
            except Exception as exc:
                logger.error(
                    "memory_extract.failed",
                    thread_id=getattr(job, "thread_id", ""),
                    task_id=getattr(job, "task_id", ""),
                    error=str(exc),
                )
            finally:
                self._queue.task_done()

    async def stop(self) -> None:
        """Signal worker to exit."""
        await self._queue.put(None)

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
        existing_texts = tuple(
            str(item.get("text", "")).strip() for item in existing if str(item.get("text", "")).strip()
        )
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
            await self._maybe_promote(job)
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
        await self._maybe_promote(job)

    async def _maybe_promote(self, job: MemoryExtractJob) -> None:
        if self._promotion is None:
            return
        scopes: list[str] = [f"thread:{job.thread_id}"]
        if job.user_id and job.user_id.strip():
            scopes.append(job.user_id.strip())
        if job.org_id and job.org_id.strip():
            scopes.append(f"org:{job.org_id.strip()}")
        for scope in scopes:
            try:
                promoted = await self._promotion.run_batch(
                    user_id=scope,
                    limit=self._promote_batch_limit,
                )
                if promoted:
                    logger.info(
                        "memory_extract.promoted",
                        thread_id=job.thread_id,
                        user_id=scope,
                        promoted=promoted,
                    )
            except Exception as exc:
                logger.warning(
                    "memory_extract.promote_failed",
                    thread_id=job.thread_id,
                    user_id=scope,
                    error=str(exc),
                )

    async def _load_excerpt(self, *, thread_id: str) -> str:
        if self._dialog_turn_store is None:
            return ""
        window = await self._dialog_turn_store.list_recent_turns(thread_id=thread_id, limit=8)
        return window.as_prompt_block()[:12000]
