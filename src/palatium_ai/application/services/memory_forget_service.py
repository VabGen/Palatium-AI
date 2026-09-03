# src/palatium_ai/application/services/memory_forget_service.py

"""User-initiated ``forget_memory`` with HITL gate (off LangGraph hot path, 020/070)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import uuid4

from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier
from palatium_ai.domain.memory.forget_payload import MemoryForgetPayload
from palatium_ai.domain.policies.memory_namespace import MemoryNamespacePolicy

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_PENDING_PREFIX = "mem_forget:pending:"
_PENDING_TTL_SECONDS = 5 * 60  # irreversible → short TTL (020)
_PLATFORM_SERVER = "platform"
_FORGET_TOOL = "forget_memory"
MEM_FORGET_TASK_PREFIX = "mem-forget-"
_VALID_NAMESPACE_KINDS = frozenset({"thread", "user", "org"})


class MemoryForgetService:
    """Create HITL card for explicit memory deletes; MCP runs only after approve."""

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
        self._memory_pending: dict[str, MemoryForgetPayload] = {}

    @traceable(name="memory_forget.request")
    async def request_forget(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
        org_id: str | None,
        namespace_kind: str,
        scope_id: str,
        entry_key: str,
    ) -> HITLCardView:
        """Validate payload, stash pending, mint mcp_tool_approval card."""
        kind = namespace_kind.strip().lower()
        if kind not in _VALID_NAMESPACE_KINDS:
            msg = "namespace_kind must be thread|user|org"
            raise ValueError(msg)

        binding = MemoryNamespacePolicy.bind_scope(
            namespace_kind=kind,
            requested_scope_id=scope_id,
            owner_user_id=owner_user_id,
            org_id=org_id,
            thread_id=thread_id,
        )
        kind = binding.namespace_kind
        scope = binding.scope_id
        key = entry_key.strip()
        if not key:
            msg = "entry_key is required"
            raise ValueError(msg)

        task_id = f"{MEM_FORGET_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = MemoryForgetPayload(
            task_id=task_id,
            thread_id=thread_id.strip(),
            user_id=owner_user_id.strip(),
            namespace_kind=kind,
            scope_id=scope,
            entry_key=key,
            org_id=(org_id or "").strip() if kind == "org" else "",
        )
        await self._store_pending(payload)

        preview = f"ns={kind}/{scope}; key={key}"
        card = await self._hitl.create_tool_approval_card(
            thread_id=thread_id.strip(),
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_FORGET_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("medium"),
            argument_preview=preview,
            owner_user_id=owner_user_id.strip(),
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        logger.info(
            "memory_forget.requested",
            task_id=task_id,
            thread_id=thread_id,
            namespace_kind=kind,
            card_id=card.card_id,
        )
        return card

    @traceable(name="memory_forget.execute_after_approval")
    async def execute_after_approval(self, *, task_id: str) -> dict[str, object]:
        """Run platform.forget_memory after HITL approve."""
        payload = await self._load_pending(task_id)
        if payload is None:
            msg = f"pending memory forget missing for task_id={task_id}"
            raise ValueError(msg)

        outcome = await call_mcp_tool(
            MCPToolCallParams(
                server_name=_PLATFORM_SERVER,
                tool_name=_FORGET_TOOL,
                arguments={
                    "user_id": payload.user_id,
                    "namespace_kind": payload.namespace_kind,
                    "scope_id": payload.scope_id,
                    "entry_key": payload.entry_key,
                    "org_id": payload.org_id,
                },
                actor_user_id=payload.user_id,
                actor_org_id=payload.org_id,
                actor_thread_id=payload.thread_id,
            ),
            self._mcp_registry,
            conversation_id=payload.thread_id,
            repository=self._mcp_tool_call_repository,
        )
        await self._delete_pending(task_id)
        if outcome.is_error:
            msg = "forget_memory MCP call failed"
            raise RuntimeError(msg)
        logger.info(
            "memory_forget.committed",
            task_id=task_id,
            thread_id=payload.thread_id,
            entry_key=payload.entry_key,
        )
        return {
            "content": outcome.content,
            "entry_key": payload.entry_key,
            "namespace_kind": payload.namespace_kind,
            "scope_id": payload.scope_id,
        }

    async def discard_pending(self, *, task_id: str) -> None:
        await self._delete_pending(task_id)

    async def _store_pending(self, payload: MemoryForgetPayload) -> None:
        key = f"{_PENDING_PREFIX}{payload.task_id}"
        raw = payload.model_dump_json()
        self._memory_pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(key, raw, ex=_PENDING_TTL_SECONDS)

    async def _load_pending(self, task_id: str) -> MemoryForgetPayload | None:
        if self._redis is None:
            return self._memory_pending.get(task_id)
        raw = await self._redis.get(f"{_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._memory_pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = MemoryForgetPayload.model_validate_json(text)
        self._memory_pending[task_id] = payload
        return payload

    async def _delete_pending(self, task_id: str) -> None:
        self._memory_pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_PENDING_PREFIX}{task_id}")
