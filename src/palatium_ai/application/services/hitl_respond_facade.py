# src/palatium_ai/application/services/hitl_respond_facade.py

"""HITL resolve + graph resume orchestration (moved out of presentation routers)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from palatium_ai.application.services.hitl_service import (
    HitlCardConflictError,
    HitlCardGoneError,
    HitlCardNotFoundError,
    HitlInvalidActionError,
)
from palatium_ai.application.services.kill_switch import KillSwitchEngagedError
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.hitl.cards import HITLCardView, HITLResolveRequest, HITLResolveResult
from palatium_ai.domain.sessions.errors import SessionOwnershipError

if TYPE_CHECKING:
    from palatium_ai.application.services.document_ingest_service import DocumentIngestService
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.application.services.intent_service import IntentService
    from palatium_ai.application.services.memory_consolidate_service import MemoryConsolidateService
    from palatium_ai.application.services.memory_forget_service import MemoryForgetService
    from palatium_ai.application.services.memory_save_service import MemorySaveService

_OFF_GRAPH_TOOL_PREFIXES: tuple[str, ...] = (
    "doc-ingest-",
    "mem-save-",
    "mem-forget-",
    "mem-consolidate-",
)


def _is_off_graph_tool_task(task_id: str) -> bool:
    return any(task_id.startswith(prefix) for prefix in _OFF_GRAPH_TOOL_PREFIXES)


class HitlRespondOutcome(BaseModel):
    """Resolve result plus optional resumed formatter output."""

    model_config = {"frozen": True}

    resolve: HITLResolveResult
    resumed: FormatterTaskResult | None = None


class HitlRespondFacade:
    """Resolve HITL cards and resume LangGraph when appropriate."""

    def __init__(
        self,
        *,
        hitl_service: HitlService,
        intent_service: IntentService,
        document_ingest_service: DocumentIngestService | None = None,
        memory_save_service: MemorySaveService | None = None,
        memory_forget_service: MemoryForgetService | None = None,
        memory_consolidate_service: MemoryConsolidateService | None = None,
    ) -> None:
        self._hitl = hitl_service
        self._intent = intent_service
        self._document_ingest = document_ingest_service
        self._memory_save = memory_save_service
        self._memory_forget = memory_forget_service
        self._memory_consolidate = memory_consolidate_service

    async def respond(
        self,
        card_id: str,
        body: HITLResolveRequest,
        *,
        actor_subject: str,
        actor_org_id: str | None,
        is_admin: bool,
        escalated: bool = False,
        acting_manager: bool = False,
    ) -> HitlRespondOutcome:
        """Resolve card and optionally resume the graph."""
        if escalated:
            resolve = await self._hitl.resolve_escalated(card_id, body, actor_subject=actor_subject)
        else:
            resolve = await self._hitl.resolve(card_id, body, actor_subject=actor_subject)

        card = await self._hitl.get_card(card_id)
        if card is None:
            raise HitlCardNotFoundError(f"HITL card not found: {card_id}")

        resumed = await self._resume_after_resolve(
            card=card,
            body=body,
            resolve=resolve,
            actor_subject=actor_subject,
            actor_org_id=actor_org_id,
            is_admin=is_admin,
            acting_manager=acting_manager,
        )
        return HitlRespondOutcome(resolve=resolve, resumed=resumed)

    async def _resume_after_resolve(
        self,
        *,
        card: HITLCardView,
        body: HITLResolveRequest,
        resolve: HITLResolveResult,
        actor_subject: str,
        actor_org_id: str | None,
        is_admin: bool,
        acting_manager: bool,
    ) -> FormatterTaskResult | None:
        if resolve.replayed:
            return None
        resume_user_id, resume_org_id = self._resume_identity(
            card,
            acting_manager=acting_manager,
            actor_subject=actor_subject,
            actor_org_id=actor_org_id,
        )
        try:
            return await self._perform_resume(
                card,
                body,
                resume_user_id=resume_user_id,
                resume_org_id=resume_org_id,
                is_admin=is_admin,
            )
        except Exception as exc:
            if card.purpose == "mcp_tool_approval" and not _is_off_graph_tool_task(card.task_id):
                await self._compensate_tool_resume_failure(card=card, cause=exc)
            raise

    def _resume_identity(
        self,
        card: HITLCardView,
        *,
        acting_manager: bool,
        actor_subject: str,
        actor_org_id: str | None,
    ) -> tuple[str, str]:
        if acting_manager:
            owner = (card.owner_user_id or "").strip()
            if not owner:
                msg = "Escalated card missing owner_user_id; cannot resume thread"
                raise ValueError(msg)
            return owner, (card.org_id or "").strip() or (actor_org_id or "")
        return actor_subject.strip(), (actor_org_id or "").strip() or (card.org_id or "").strip()

    @staticmethod
    async def _resolve_pending_mutation(
        service: object | None,
        *,
        action_id: str,
        task_id: str,
    ) -> None:
        """Approve/reject a pending mutation service when configured."""
        if service is None:
            return
        if action_id == "approve":
            execute = getattr(service, "execute_after_approval", None)
            if execute is not None:
                await execute(task_id=task_id)
            return
        if action_id == "reject":
            discard = getattr(service, "discard_pending", None)
            if discard is not None:
                await discard(task_id=task_id)

    def _pending_mutation_service(self, task_id: str) -> object | None:
        """Resolve pending mutation service for an off-graph tool task id."""
        if task_id.startswith("doc-ingest-"):
            return self._document_ingest
        if task_id.startswith("mem-save-"):
            return self._memory_save
        if task_id.startswith("mem-forget-"):
            return self._memory_forget
        if task_id.startswith("mem-consolidate-"):
            return self._memory_consolidate
        return None

    async def _perform_resume(
        self,
        card: HITLCardView,
        body: HITLResolveRequest,
        *,
        resume_user_id: str,
        resume_org_id: str,
        is_admin: bool,
    ) -> FormatterTaskResult | None:
        if card.purpose == "mcp_tool_approval":
            if _is_off_graph_tool_task(card.task_id):
                await self._resolve_pending_mutation(
                    self._pending_mutation_service(card.task_id),
                    action_id=body.action_id,
                    task_id=card.task_id,
                )
                return None
            return await self._intent.resume_after_tool_approval(
                thread_id=card.thread_id,
                task_id=card.task_id,
                action_id=body.action_id,
                user_id=resume_user_id,
                org_id=resume_org_id,
                is_admin=is_admin,
            )
        if card.purpose == "user_choice":
            return await self._intent.process_hitl_choice(
                thread_id=card.thread_id,
                action_id=body.action_id,
                card=card,
                user_id=resume_user_id,
                org_id=resume_org_id,
                is_admin=is_admin,
            )
        if card.purpose == "quality_review":
            return await self._resume_quality_review(
                card,
                body,
                resume_user_id=resume_user_id,
                resume_org_id=resume_org_id,
                is_admin=is_admin,
            )
        return None

    async def _resume_quality_review(
        self,
        card: HITLCardView,
        body: HITLResolveRequest,
        *,
        resume_user_id: str,
        resume_org_id: str,
        is_admin: bool,
    ) -> FormatterTaskResult | None:
        if body.action_id == "reject":
            return await self._intent.revise_after_quality_reject(
                thread_id=card.thread_id,
                task_id=card.task_id,
                user_id=resume_user_id,
                org_id=resume_org_id,
                is_admin=is_admin,
            )
        if body.action_id == "approve":
            await self._intent.acknowledge_quality_approve(
                thread_id=card.thread_id,
                user_id=resume_user_id,
                is_admin=is_admin,
                content_sha256=card.content_sha256,
            )
        return None

    async def _compensate_tool_resume_failure(
        self,
        *,
        card: HITLCardView,
        cause: BaseException,
    ) -> None:
        try:
            await self._intent.deny_tool_interrupt(
                thread_id=card.thread_id,
                task_id=card.task_id,
                card_id=card.card_id,
                reason=f"resume_failed:{type(cause).__name__}",
            )
            agent_metrics.record_hitl_deny("resume_compensated_deny")
        except Exception:
            agent_metrics.record_hitl_deny("resume_compensate_failed")


__all__ = [
    "HitlCardConflictError",
    "HitlCardGoneError",
    "HitlCardNotFoundError",
    "HitlInvalidActionError",
    "HitlRespondFacade",
    "HitlRespondOutcome",
    "KillSwitchEngagedError",
    "SessionOwnershipError",
]
