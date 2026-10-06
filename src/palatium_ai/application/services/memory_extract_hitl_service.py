# src/palatium_ai/application/services/memory_extract_hitl_service.py

"""HITL gate for MCP ``extract_transcript_memories`` (enqueue sleep-time extract).

Does not write the graph. Graph growth is ``MemoryPromotionService`` (promote axis).
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier
from palatium_ai.domain.memory.extract_enqueue_payload import MemoryExtractEnqueuePayload

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_PENDING_PREFIX = "mem_extract:pending:"
_PENDING_TTL_SECONDS = 5 * 60  # write enqueue → short TTL (020)
_PLATFORM_SERVER = "platform"
_EXTRACT_TOOL = "extract_transcript_memories"
MEM_EXTRACT_TASK_PREFIX = "mem-extract-"
# Back-compat alias for imports until callers migrate.
MEM_CONSOLIDATE_TASK_PREFIX = MEM_EXTRACT_TASK_PREFIX


class MemoryExtractHitlService:
    """Mint HITL card for user-initiated extract enqueue; MCP runs only after approve."""

    def __init__(
        self,
        *,
        hitl_service: HitlService,
        mcp_registry: MCPRegistryPort,
        redis_client: Redis | None = None,
        mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
    ) -> None:
        self._hitl = hitl_service
        self._mcp_registry = mcp_registry
        self._redis = redis_client
        self._mcp_tool_call_repository = mcp_tool_call_repository
        self._memory_pending: dict[str, MemoryExtractEnqueuePayload] = {}

    @traceable(name="memory_extract_hitl.request")
    async def request_extract(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
        org_id: str | None,
        extract_task_id: str = "",
    ) -> HITLCardView:
        """Validate payload, stash pending, mint mcp_tool_approval card (extract enqueue)."""
        thread = thread_id.strip()
        if not thread:
            msg = "thread_id is required"
            raise ValueError(msg)
        user = owner_user_id.strip()
        if not user:
            msg = "owner_user_id is required"
            raise ValueError(msg)

        task_id = f"{MEM_EXTRACT_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = MemoryExtractEnqueuePayload(
            task_id=task_id,
            thread_id=thread,
            user_id=user,
            org_id=(org_id or "").strip(),
            extract_task_id=extract_task_id.strip(),
        )
        await self._store_pending(payload)

        preview = f"extract enqueue; thread={thread}; user={user}; org={payload.org_id or '-'}"
        card = await self._hitl.create_tool_approval_card(
            thread_id=thread,
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_EXTRACT_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("medium"),
            argument_preview=preview,
            owner_user_id=user,
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        logger.info(
            "memory_extract_hitl.requested",
            task_id=task_id,
            thread_id=thread,
            card_id=card.card_id,
        )
        return card

    @traceable(name="memory_extract_hitl.execute_after_approval")
    async def execute_after_approval(self, *, task_id: str) -> dict[str, object]:
        """Run platform.extract_transcript_memories after HITL approve."""
        payload = await self._load_pending(task_id)
        if payload is None:
            msg = f"pending memory extract enqueue missing for task_id={task_id}"
            raise ValueError(msg)

        arguments: dict[str, object] = {
            "user_id": payload.user_id,
            "thread_id": payload.thread_id,
        }
        if payload.org_id:
            arguments["org_id"] = payload.org_id
        if payload.extract_task_id:
            arguments["task_id"] = payload.extract_task_id

        outcome = await call_mcp_tool(
            MCPToolCallParams(
                server_name=_PLATFORM_SERVER,
                tool_name=_EXTRACT_TOOL,
                arguments=arguments,
                actor_user_id=payload.user_id,
                actor_org_id=payload.org_id or "",
                actor_thread_id=payload.thread_id,
            ),
            self._mcp_registry,
            conversation_id=payload.thread_id,
            repository=self._mcp_tool_call_repository,
        )
        await self._delete_pending(task_id)
        if outcome.is_error:
            msg = "extract_transcript_memories MCP call failed (extract enqueue)"
            raise RuntimeError(msg)
        logger.info(
            "memory_extract_hitl.queued",
            task_id=task_id,
            thread_id=payload.thread_id,
        )
        return {
            "content": outcome.content,
            "thread_id": payload.thread_id,
            "user_id": payload.user_id,
        }

    async def discard_pending(self, *, task_id: str) -> None:
        await self._delete_pending(task_id)

    async def _store_pending(self, payload: MemoryExtractEnqueuePayload) -> None:
        key = f"{_PENDING_PREFIX}{payload.task_id}"
        raw = payload.model_dump_json()
        self._memory_pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(key, raw, ex=_PENDING_TTL_SECONDS)

    async def _load_pending(self, task_id: str) -> MemoryExtractEnqueuePayload | None:
        if self._redis is None:
            return self._memory_pending.get(task_id)
        raw = await self._redis.get(f"{_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._memory_pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = MemoryExtractEnqueuePayload.model_validate_json(text)
        self._memory_pending[task_id] = payload
        return payload

    async def _delete_pending(self, task_id: str) -> None:
        self._memory_pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_PENDING_PREFIX}{task_id}")


# Back-compat alias (prefer MemoryExtractHitlService).
MemoryConsolidateService = MemoryExtractHitlService
