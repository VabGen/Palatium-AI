# src/palatium_ai/application/services/skill_manage_service.py

"""User-initiated ``skill_manage`` with HITL gate (off LangGraph hot path, 020/070)."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast
from uuid import uuid4

from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier
from palatium_ai.domain.skills.frontmatter import is_safe_skill_name
from palatium_ai.domain.skills.lint import lint_skill_markdown
from palatium_ai.domain.skills.manage_payload import SkillManageAction, SkillManagePayload

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_PENDING_PREFIX = "skill_manage:pending:"
_PENDING_TTL_SECONDS = 30 * 60
_PLATFORM_SERVER = "platform"
_MANAGE_TOOL = "skill_manage"
MEM_SKILL_TASK_PREFIX = "skill-manage-"
_VALID_ACTIONS = frozenset({"create", "update", "delete"})


class SkillManageService:
    """Create HITL card for skill create/update/delete; MCP runs only after approve."""

    def __init__(
        self,
        *,
        hitl_service: HitlService,
        mcp_registry: MCPRegistryPort,
        enabled: bool = False,
        redis_client: Redis | None = None,
        mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
    ) -> None:
        self._hitl = hitl_service
        self._mcp_registry = mcp_registry
        self._enabled = bool(enabled)
        self._redis = redis_client
        self._mcp_tool_call_repository = mcp_tool_call_repository
        self._pending: dict[str, SkillManagePayload] = {}

    @property
    def enabled(self) -> bool:
        return self._enabled

    @traceable(name="skill_manage.request")
    async def request_manage(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
        org_id: str | None,
        action: str,
        skill_name: str,
        content: str = "",
        description: str = "",
    ) -> HITLCardView:
        """Validate + lint (for write actions), stash pending, mint approval card."""
        if not self._enabled:
            msg = "Feature disabled"
            raise ValueError(msg)

        action_norm = action.strip().lower()
        if action_norm not in _VALID_ACTIONS:
            msg = "action must be create|update|delete"
            raise ValueError(msg)
        name = skill_name.strip()
        if not is_safe_skill_name(name):
            msg = "skill_name must match [a-z0-9][a-z0-9_-]{0,63}"
            raise ValueError(msg)

        content_value = content if isinstance(content, str) else ""
        description_value = description.strip() if isinstance(description, str) else ""
        if action_norm in {"create", "update"}:
            lint = lint_skill_markdown(
                content_value,
                expected_name=name,
                expected_description=description_value or None,
            )
            if not lint.ok:
                msg = "skill lint failed: " + "; ".join(lint.errors)
                raise ValueError(msg)

        task_id = f"{MEM_SKILL_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = SkillManagePayload(
            task_id=task_id,
            thread_id=thread_id.strip(),
            user_id=owner_user_id.strip(),
            action=cast("SkillManageAction", action_norm),
            skill_name=name,
            content=content_value,
            description=description_value,
            org_id=(org_id or "").strip(),
        )
        await self._store_pending(payload)

        preview = f"action={action_norm}; skill={name}"
        if description_value:
            preview += f"; desc={description_value[:80]}"
        card = await self._hitl.create_tool_approval_card(
            thread_id=thread_id.strip(),
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_MANAGE_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("high"),
            argument_preview=preview,
            owner_user_id=owner_user_id.strip(),
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        logger.info(
            "skill_manage.requested",
            task_id=task_id,
            action=action_norm,
            skill_name=name,
            card_id=card.card_id,
        )
        return card

    @traceable(name="skill_manage.execute_after_approval")
    async def execute_after_approval(self, *, task_id: str) -> dict[str, object]:
        """Run platform.skill_manage after HITL approve."""
        payload = await self._load_pending(task_id)
        if payload is None:
            msg = f"pending skill_manage missing for task_id={task_id}"
            raise ValueError(msg)
        if not self._enabled:
            msg = "Feature disabled"
            raise ValueError(msg)

        outcome = await call_mcp_tool(
            MCPToolCallParams(
                server_name=_PLATFORM_SERVER,
                tool_name=_MANAGE_TOOL,
                arguments={
                    "action": payload.action,
                    "skill_name": payload.skill_name,
                    "content": payload.content,
                    "description": payload.description,
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
            msg = "skill_manage MCP call failed"
            raise RuntimeError(msg)
        logger.info(
            "skill_manage.committed",
            task_id=task_id,
            action=payload.action,
            skill_name=payload.skill_name,
        )
        return {
            "content": outcome.content,
            "action": payload.action,
            "skill_name": payload.skill_name,
            "summary": f"Навык {payload.skill_name}: {payload.action} выполнен.",
        }

    async def discard_pending(self, *, task_id: str) -> None:
        await self._delete_pending(task_id)

    async def _store_pending(self, payload: SkillManagePayload) -> None:
        key = f"{_PENDING_PREFIX}{payload.task_id}"
        raw = payload.model_dump_json()
        self._pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(key, raw, ex=_PENDING_TTL_SECONDS)

    async def _load_pending(self, task_id: str) -> SkillManagePayload | None:
        if self._redis is None:
            return self._pending.get(task_id)
        raw = await self._redis.get(f"{_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = SkillManagePayload.model_validate_json(text)
        self._pending[task_id] = payload
        return payload

    async def _delete_pending(self, task_id: str) -> None:
        self._pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_PENDING_PREFIX}{task_id}")
