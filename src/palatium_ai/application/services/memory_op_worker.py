# src/palatium_ai/application/services/memory_op_worker.py

"""Background drain for MemoryOpQueue: promote_entry | clear_user_graph (W11)."""

from __future__ import annotations

import asyncio
import json

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.domain.memory.promotion import PromotionCandidate
from palatium_ai.domain.memory.types import resolve_memory_trust

if TYPE_CHECKING:
    from palatium_ai.application.services.memory_promotion import MemoryPromotionService
    from palatium_ai.domain.graph.write_port import GraphWritePort
    from palatium_ai.domain.memory.memory_op_queue import MemoryOpQueuePort, MemoryOpRecord
    from palatium_ai.domain.memory.ports import MemoryPort

logger = get_logger(__name__)

_DEFAULT_POLL_SECONDS = 0.5
_CLEAR_PAGE_LIMIT = 64


class MemoryOpWorker:
    """Claim SKIP LOCKED ops until stop(); Neo4j I/O stays off the request span."""

    def __init__(
        self,
        *,
        queue: MemoryOpQueuePort,
        memory_port: MemoryPort,
        graph_write: GraphWritePort,
        promotion: MemoryPromotionService,
        promote_fast_min_score: float = 0.85,
        poll_seconds: float = _DEFAULT_POLL_SECONDS,
    ) -> None:
        self._queue = queue
        self._memory = memory_port
        self._graph = graph_write
        self._promotion = promotion
        self._fast_min = max(0.0, min(1.0, promote_fast_min_score))
        self._poll_seconds = max(0.05, poll_seconds)
        self._stop = asyncio.Event()

    async def stop(self) -> None:
        self._stop.set()

    @traceable(name="memory_op_worker.run")
    async def run(self) -> None:
        self._stop.clear()
        while not self._stop.is_set():
            try:
                record = await self._queue.claim()
                if record is None:
                    try:
                        await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
                    except TimeoutError:
                        continue
                    break
                await self._run_claimed(record)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001  # worker keeps draining after unexpected errors
                logger.error(
                    "memory_op_worker.loop_error",
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                await asyncio.sleep(self._poll_seconds)

    async def _run_claimed(self, record: MemoryOpRecord) -> None:
        try:
            # ``MemoryOpRecord.kind`` is validated to ``MemoryOpKind`` at the row
            # boundary, so this match is exhaustive by contract — no dead branch.
            match record.kind:
                case "promote_entry":
                    await self._handle_promote(record)
                case "clear_user_graph":
                    await self._handle_clear_graph(record)
            await self._queue.complete(record.id)
        except Exception as exc:  # noqa: BLE001  # failed op is marked; worker continues
            logger.error(
                "memory_op_worker.failed",
                kind=record.kind,
                op_id=str(record.id),
                user_id=record.user_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            await self._queue.fail(record.id, error=str(exc))

    async def _handle_promote(self, record: MemoryOpRecord) -> None:
        namespace = _decode_namespace(record.namespace_json)
        if not namespace or not record.entry_key:
            msg = "promote_entry requires namespace and entry_key"
            raise ValueError(msg)
        value = await self._memory.get(namespace=namespace, key=record.entry_key)
        if value is None:
            logger.info(
                "memory_op_worker.promote_missing",
                entry_key=record.entry_key,
                user_id=record.user_id,
                reason=record.reason or "immediate_verified",
            )
            return
        candidate = _candidate_from_value(
            namespace=namespace,
            entry_key=record.entry_key,
            user_id=record.user_id,
            value=value,
        )
        outcome = await self._promotion.promote_verified_fast(
            candidate,
            min_score=self._fast_min,
            reason=record.reason or "immediate_verified",
        )
        logger.info(
            "memory_op_worker.promote_done",
            entry_key=record.entry_key,
            user_id=record.user_id,
            outcome=outcome,
            reason=record.reason or "immediate_verified",
        )

    async def _handle_clear_graph(self, record: MemoryOpRecord) -> None:
        expired = 0
        while True:
            facts = await self._graph.list_active_facts(
                user_id=record.user_id,
                limit=_CLEAR_PAGE_LIMIT,
            )
            if not facts:
                break
            batch = 0
            for fact in facts:
                if await self._graph.expire_fact(user_id=record.user_id, entry_key=fact.entry_key):
                    batch += 1
                    expired += 1
            if batch == 0:
                break
        logger.info(
            "memory_op_worker.clear_user_graph_done",
            user_id=record.user_id,
            expired=expired,
            reason=record.reason or "user_clear",
        )


def _decode_namespace(raw: str) -> tuple[str, ...]:
    try:
        parsed = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return ()
    if not isinstance(parsed, list):
        return ()
    return tuple(str(part) for part in parsed)


def _candidate_from_value(
    *,
    namespace: tuple[str, ...],
    entry_key: str,
    user_id: str,
    value: dict[str, object],
) -> PromotionCandidate:
    text = str(value.get("text", "")).strip()
    importance = max(0.0, min(1.0, coerce_float(value.get("importance", value.get("confidence", 0.0)))))
    confidence = max(0.0, min(1.0, coerce_float(value.get("confidence", 0.0))))
    access = int(coerce_float(value.get("access_frequency", 0)))
    return PromotionCandidate(
        namespace=namespace,
        entry_key=entry_key,
        text=text[:2000] or entry_key,
        kind=str(value.get("kind", "fact"))[:32],
        importance=importance,
        access_frequency=max(0, access),
        user_id=user_id,
        confidence=confidence,
        contains_pii=bool(value.get("contains_pii", False)),
        trust=resolve_memory_trust(value),
    )


# Re-export for typing convenience in tests
__all__ = ["MemoryOpWorker"]
