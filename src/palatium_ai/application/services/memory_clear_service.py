# src/palatium_ai/application/services/memory_clear_service.py

"""HITL-gated clear of Medium memory + enqueue Neo4j cascade (W11, 020)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier
from palatium_ai.domain.memory.clear_payload import MemoryClearPayload

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.memory.memory_op_queue import MemoryOpQueuePort
    from palatium_ai.domain.memory.ports import MemoryPort

logger = get_logger(__name__)

_PENDING_PREFIX = "mem_clear:pending:"
_PENDING_TTL_SECONDS = 5 * 60  # irreversible → short TTL (020)
_PLATFORM_SERVER = "platform"
_CLEAR_TOOL = "clear_memory"
MEM_CLEAR_TASK_PREFIX = "mem-clear-"


async def _audit(event: str, *, conversation_id: str, metadata: dict[str, str]) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        await get_audit_logger().append_async(
            timestamp=timestamp,
            conversation_id=conversation_id,
            event=event,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001  # audit is best-effort; clear must proceed (040)
        logger.warning("memory_clear.audit_failed", audit_event=event, error=str(exc))


class MemoryClearService:
    """Mint HITL card; on approve purge Medium scopes + enqueue clear_user_graph."""

    def __init__(
        self,
        *,
        hitl_service: HitlService,
        memory_port: MemoryPort,
        memory_op_queue: MemoryOpQueuePort,
        redis_client: Redis | None = None,
    ) -> None:
        self._hitl = hitl_service
        self._memory_port = memory_port
        self._ops = memory_op_queue
        self._redis = redis_client
        self._pending: dict[str, MemoryClearPayload] = {}

    @traceable(name="memory_clear.request")
    async def request_clear(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
        org_id: str | None,
    ) -> HITLCardView:
        uid = owner_user_id.strip()
        if not uid:
            msg = "owner_user_id is required"
            raise ValueError(msg)
        tid = thread_id.strip()
        if not tid:
            msg = "thread_id is required"
            raise ValueError(msg)
        task_id = f"{MEM_CLEAR_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = MemoryClearPayload(
            task_id=task_id,
            thread_id=tid,
            user_id=uid,
            org_id=(org_id or "").strip(),
        )
        await self._store_pending(payload)
        await _audit(
            "memory_clear_requested",
            conversation_id=tid,
            metadata={"task_id": task_id, "user_id": uid},
        )
        card = await self._hitl.create_tool_approval_card(
            thread_id=tid,
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_CLEAR_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("high"),
            argument_preview=f"clear medium+L4 for user={uid}",
            owner_user_id=uid,
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        logger.info(
            "memory_clear.requested",
            task_id=task_id,
            thread_id=tid,
            card_id=card.card_id,
        )
        return card

    @traceable(name="memory_clear.execute_after_approval")
    async def execute_after_approval(self, *, task_id: str) -> dict[str, object]:
        payload = await self._load_pending(task_id)
        if payload is None:
            msg = f"pending memory clear missing for task_id={task_id}"
            raise ValueError(msg)

        # Full Clear Memories for the principal (ChatGPT analogue): all Medium scopes.
        deleted = await self._memory_port.clear_namespace(user_id=payload.user_id, namespaces=None)
        enqueue_result = await self._ops.enqueue(
            kind="clear_user_graph",
            user_id=payload.user_id,
            reason="user_clear",
        )
        await self._delete_pending(task_id)
        await _audit(
            "memory_clear_committed",
            conversation_id=payload.thread_id,
            metadata={
                "task_id": task_id,
                "user_id": payload.user_id,
                "deleted": str(deleted),
                "graph_enqueue": enqueue_result,
            },
        )
        logger.info(
            "memory_clear.committed",
            task_id=task_id,
            thread_id=payload.thread_id,
            deleted=deleted,
            graph_enqueue=enqueue_result,
        )
        return {
            "deleted": deleted,
            "graph_enqueue": enqueue_result,
            "summary": "Память очищена; граф будет обновлён в фоне.",
        }

    async def discard_pending(self, *, task_id: str) -> None:
        await self._delete_pending(task_id)

    async def _store_pending(self, payload: MemoryClearPayload) -> None:
        key = f"{_PENDING_PREFIX}{payload.task_id}"
        self._pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(key, payload.model_dump_json(), ex=_PENDING_TTL_SECONDS)

    async def _load_pending(self, task_id: str) -> MemoryClearPayload | None:
        if self._redis is None:
            return self._pending.get(task_id)
        raw = await self._redis.get(f"{_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = MemoryClearPayload.model_validate_json(text)
        self._pending[task_id] = payload
        return payload

    async def _delete_pending(self, task_id: str) -> None:
        self._pending.pop(task_id, None)
        if self._redis is None:
            return
        await self._redis.delete(f"{_PENDING_PREFIX}{task_id}")
