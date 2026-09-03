# src/palatium_ai/application/services/memory_consolidate_service.py

"""User-initiated ``consolidate_memory`` with HITL gate (off LangGraph hot path, 020/070)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier
from palatium_ai.domain.memory.consolidate_payload import MemoryConsolidatePayload

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_PENDING_PREFIX = "mem_consolidate:pending:"
_PENDING_TTL_SECONDS = 5 * 60  # long-term write → short TTL (020)
_PLATFORM_SERVER = "platform"
_CONSOLIDATE_TOOL = "consolidate_memory"
MEM_CONSOLIDATE_TASK_PREFIX = "mem-consolidate-"


class MemoryConsolidateService:
    """Create HITL card for explicit consolidation enqueue; MCP runs only after approve."""

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
        self._memory_pending: dict[str, MemoryConsolidatePayload] = {}

    @traceable(name="memory_consolidate.request")
    async def request_consolidate(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
        org_id: str | None,
        consolidate_task_id: str = "",
    ) -> HITLCardView:
        """Validate payload, stash pending, mint mcp_tool_approval card."""
        thread = thread_id.strip()
        if not thread:
            msg = "thread_id is required"
            raise ValueError(msg)
        user = owner_user_id.strip()
        if not user:
            msg = "owner_user_id is required"
            raise ValueError(msg)

        task_id = f"{MEM_CONSOLIDATE_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = MemoryConsolidatePayload(
            task_id=task_id,
            thread_id=thread,
            user_id=user,
            org_id=(org_id or "").strip(),
            consolidate_task_id=consolidate_task_id.strip(),
        )
        await self._store_pending(payload)

        preview = f"thread={thread}; user={user}; org={payload.org_id or '-'}"
        card = await self._hitl.create_tool_approval_card(
            thread_id=thread,
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_CONSOLIDATE_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("medium"),
            argument_preview=preview,
            owner_user_id=user,
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        logger.info(
            "memory_consolidate.requested",
            task_id=task_id,
            thread_id=thread,
            card_id=card.card_id,
        )
        return card

    @traceable(name="memory_consolidate.execute_after_approval")
    async def execute_after_approval(self, *, task_id: str) -> dict[str, object]:
        """Run platform.consolidate_memory after HITL approve (enqueues sleep-time job)."""
        payload = await self._load_pending(task_id)
        if payload is None:
            msg = f"pending memory consolidate missing for task_id={task_id}"
            raise ValueError(msg)

        arguments: dict[str, object] = {
            "user_id": payload.user_id,
            "thread_id": payload.thread_id,
        }
        if payload.org_id:
            arguments["org_id"] = payload.org_id
        if payload.consolidate_task_id:
            arguments["task_id"] = payload.consolidate_task_id

        outcome = await call_mcp_tool(
            MCPToolCallParams(
                server_name=_PLATFORM_SERVER,
                tool_name=_CONSOLIDATE_TOOL,
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
            msg = "consolidate_memory MCP call failed"
            raise RuntimeError(msg)
        logger.info(
            "memory_consolidate.queued",
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

    async def _store_pending(self, payload: MemoryConsolidatePayload) -> None:
        key = f"{_PENDING_PREFIX}{payload.task_id}"
        raw = payload.model_dump_json()
        self._memory_pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(key, raw, ex=_PENDING_TTL_SECONDS)

    async def _load_pending(self, task_id: str) -> MemoryConsolidatePayload | None:
        if self._redis is None:
            return self._memory_pending.get(task_id)
        raw = await self._redis.get(f"{_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._memory_pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = MemoryConsolidatePayload.model_validate_json(text)
        self._memory_pending[task_id] = payload
        return payload

    async def _delete_pending(self, task_id: str) -> None:
        self._memory_pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_PENDING_PREFIX}{task_id}")
