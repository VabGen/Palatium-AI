# src/palatium_ai/application/services/intent_service.py

"""Use case: классификация намерения через LangGraph + dialog memory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from time import perf_counter
from typing import TYPE_CHECKING, Any, Literal, cast
from uuid import UUID, uuid4

from palatium_ai.application.services.cost_budget import CostBudgetService
from palatium_ai.application.services.intent_graph_runner import IntentGraphRunner
from palatium_ai.application.services.intent_hitl_flow import (
    _MAX_QUALITY_REVISIONS,
    IntentHitlFlow,
    max_quality_revisions,
)
from palatium_ai.application.services.intent_turn_helpers import (
    PENDING_ATTACHMENT_IDS_KEY,
    assistant_turn_content as _assistant_turn_content,
    assistant_turn_payload as _assistant_turn_payload,
    derive_session_title as _derive_session_title,
    extract_interrupt as _extract_interrupt,
    parse_pending_attachment_ids,
    serialize_pending_attachment_ids,
    snapshot_awaits_resume as _snapshot_awaits_resume,
    tenant_budget_key as _tenant_budget_key,
    write_audit as _write_audit,
)
from palatium_ai.application.services.kill_switch import KillSwitchService
from palatium_ai.application.services.response_cache_service import ResponseCacheService
from palatium_ai.application.services.session_scratchpad import SessionScratchpadService
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentTaskResult
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.policies.locale import ReplyLocalePolicy
from palatium_ai.domain.sessions.context_privacy import session_user_text_preview

_DEFAULT_DIALOG_WINDOW = 12

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from palatium_ai.application.orchestration.state import AgentGraphState
    from palatium_ai.application.services.attachment_service import AttachmentService
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.application.services.memory_extract import MemoryExtractService
    from palatium_ai.application.services.option_synthesizer import OptionSynthesizer
    from palatium_ai.application.services.session_service import SessionService
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort

logger = get_logger(__name__)

__all__ = [
    "_MAX_QUALITY_REVISIONS",
    "IntentService",
    "_assistant_turn_content",
    "_assistant_turn_payload",
    "_snapshot_awaits_resume",
    "max_quality_revisions",
]


class IntentService:
    """Оркестрирует классификацию намерений через StateGraph."""

    def __init__(
        self,
        graph: CompiledStateGraph[AgentGraphState],
        *,
        session_service: SessionService,
        hitl_service: HitlService,
        kill_switch: KillSwitchService | None = None,
        cost_budget: CostBudgetService | None = None,
        dialog_turn_store: DialogTurnStore | None = None,
        memory_port: MemoryPort | None = None,
        consolidation: MemoryExtractService | None = None,
        option_synthesizer: OptionSynthesizer | None = None,
        dialog_window_size: int = _DEFAULT_DIALOG_WINDOW,
        recall_min_confidence: float = 0.7,
        recall_max_items: int = 4,
        recall_max_chars: int = 800,
        contextualizer_dialog_max_chars: int = 6000,
        worker_summary_max_chars: int = 4000,
        mcp_tool_output_max_chars: int = 3000,
        turn_hop_budget_ms: int = 15_000,
        attachment_service: AttachmentService | None = None,
        response_cache: ResponseCacheService | None = None,
    ) -> None:
        self._session_service = session_service
        self._hitl_service = hitl_service
        self._kill_switch = kill_switch or KillSwitchService()
        self._cost_budget = cost_budget or CostBudgetService()
        self._dialog_turn_store = dialog_turn_store
        self._memory_port = memory_port
        self._consolidation = consolidation
        self._option_synthesizer = option_synthesizer
        self._attachment_service = attachment_service
        self._response_cache = response_cache or ResponseCacheService(None, enabled=False)

        self._graph_runner = IntentGraphRunner(
            graph,
            session_service=session_service,
            cost_budget=self._cost_budget,
            dialog_turn_store=dialog_turn_store,
            memory_port=memory_port,
            consolidation=consolidation,
            scratchpad=SessionScratchpadService(memory_port),
            dialog_window_size=dialog_window_size,
            recall_min_confidence=recall_min_confidence,
            recall_max_items=recall_max_items,
            recall_max_chars=recall_max_chars,
            contextualizer_dialog_max_chars=contextualizer_dialog_max_chars,
            worker_summary_max_chars=worker_summary_max_chars,
            mcp_tool_output_max_chars=mcp_tool_output_max_chars,
            turn_hop_budget_ms=turn_hop_budget_ms,
        )
        self._hitl_flow = IntentHitlFlow(
            graph_runner=self._graph_runner,
            session_service=session_service,
            hitl_service=hitl_service,
            kill_switch=self._kill_switch,
            cost_budget=self._cost_budget,
            process_turn=self.process,
            dialog_turn_store=dialog_turn_store,
            consolidation=consolidation,
            option_synthesizer=option_synthesizer,
        )
        self._graph_runner.bind_attach_hitl_cards(self._hitl_flow.attach_hitl_cards)

    async def _turn_untrusted_context(
        self,
        attachment_ids: Sequence[UUID] | None,
        *,
        thread_id: str,
        user_id: str | None,
    ) -> str:
        """Resolve this turn's fenced attachment text (020).

        Attachments are optional: with no service wired or no ids the turn runs
        exactly as before. When ids are present the block is resolved through
        ``AttachmentService``, which re-runs the injection policy and returns
        text already wrapped in the untrusted fence; ``AttachmentError``
        propagates to the API boundary so the caller sees a typed refusal
        instead of a turn that silently drops the user's file.
        """
        if self._attachment_service is None or not attachment_ids:
            if attachment_ids and self._attachment_service is None:
                logger.warning(
                    "attachment.turn_context_skipped",
                    thread_id=thread_id,
                    reason="attachment_service_unavailable",
                    attachment_count=len(attachment_ids),
                )
            return ""
        context = await self._attachment_service.build_turn_context(
            attachment_ids=list(attachment_ids),
            user_id=user_id or "",
            thread_id=thread_id,
        )
        return context.fenced_text

    @staticmethod
    def _serialize_pending_attachment_ids(attachment_ids: Sequence[UUID]) -> str:
        return serialize_pending_attachment_ids(list(attachment_ids))

    @staticmethod
    def _parse_pending_attachment_ids(raw: object) -> list[UUID]:
        return parse_pending_attachment_ids(raw)

    async def _pending_attachment_ids(self, *, thread_id: str) -> list[UUID]:
        session = await self._session_service.get_session(thread_id=thread_id)
        if session is None or not isinstance(session.context, dict):
            return []
        return self._parse_pending_attachment_ids(session.context.get(PENDING_ATTACHMENT_IDS_KEY))

    async def _resolve_turn_attachment_ids(
        self,
        attachment_ids: Sequence[UUID] | None,
        *,
        thread_id: str,
        restore_pending: bool = False,
    ) -> list[UUID] | None:
        """Explicit upload ids win; otherwise restore sticky session attachments.

        Composer chips clear after send (UI), but follow-ups like «дай сводку»
        still refer to the last ready uploads — restore ``pending_attachment_ids``
        from the session when ``restore_pending`` is True (process / HITL resume).
        """
        if attachment_ids:
            return list(attachment_ids)
        if not restore_pending:
            return None
        pending = await self._pending_attachment_ids(thread_id=thread_id)
        return pending or None

    def _attachment_context_patch(self, attachment_ids: Sequence[UUID] | None) -> dict[str, object]:
        if not attachment_ids:
            return {}
        return {PENDING_ATTACHMENT_IDS_KEY: self._serialize_pending_attachment_ids(attachment_ids)}

    @traceable(name="intent_service.classify")
    async def classify(
        self,
        text: str,
        thread_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        *,
        is_admin: bool = False,
        attachment_ids: Sequence[UUID] | None = None,
    ) -> IntentTaskResult:
        """Возвращает platform-level классификацию задачи."""
        resolved_task_id = task_id or str(uuid4())
        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=True,
        )
        await self._kill_switch.assert_clear(conversation_id=thread_id)
        await self._cost_budget.assert_daily_allows_turn(
            tenant_key=_tenant_budget_key(user_id=user_id, org_id=org_id, thread_id=thread_id)
        )
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            title=_derive_session_title(text),
            context_patch={
                "last_operation": "classify",
                "last_task_id": resolved_task_id,
                "last_user_text": session_user_text_preview(text),
                "org_id": org_id or "",
            },
        )
        final_state = await self._graph_runner.run_graph(
            text=text,
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=_tenant_budget_key(user_id=user_id, org_id=org_id, thread_id=thread_id),
            untrusted_context=await self._turn_untrusted_context(
                attachment_ids,
                thread_id=thread_id,
                user_id=user_id,
            ),
        )
        classification = final_state.get("classification")
        critic = final_state.get("critic")
        execution = final_state.get("execution")

        if not isinstance(classification, IntentTaskResult):
            failure_result = IntentTaskResult(
                task_id=resolved_task_id,
                agent_role="intent_classifier",
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=None,
                error="Graph did not produce classification result",
            )
            await self._session_service.touch_session(
                thread_id=thread_id,
                context_patch={
                    "last_operation": "classify",
                    "last_task_id": resolved_task_id,
                    "last_task_kind": "clarification_needed",
                    "candidate_capabilities": [],
                    "requires_mcp": False,
                    "last_status": failure_result.status,
                    "requires_review": failure_result.requires_review,
                    "escalation_reason": "missing_classification_result",
                    "last_error": failure_result.error or "",
                },
                status="needs_review",
            )
            await _write_audit(
                conversation_id=thread_id,
                event="intent_classify_completed",
                metadata={
                    "status": failure_result.status,
                    "task_kind": "clarification_needed",
                    "requires_review": str(failure_result.requires_review),
                },
            )
            return failure_result

        requires_review = classification.requires_review
        status: Literal["success", "failure", "partial"] = classification.status
        escalation_reason = ""
        critic_requires_review = False
        if critic is not None:
            critic_requires_review = bool(getattr(critic, "requires_review", False))
            if critic_requires_review:
                requires_review = True
                escalation_reason = "critic_requires_review"
                if status == "success":
                    status = "partial"
                agent_metrics.record_human_escalation("critic_requires_review")

        routing_intent = final_state.get("routing_intent")
        if routing_intent is not None and classification.output is not None:
            # ContinuityPolicy is the routing source of truth (not raw Intent axes).
            if routing_intent.suppress_intent_hitl and not critic_requires_review:
                requires_review = False
                if status == "partial" and classification.status == "partial":
                    status = "success"
            classification = IntentTaskResult(
                task_id=classification.task_id,
                agent_role=classification.agent_role,
                status=status,
                confidence=classification.confidence,
                requires_review=requires_review,
                output=classification.output.model_copy(
                    update={
                        "task_kind": routing_intent.task_kind,
                        "requires_mcp": routing_intent.requires_mcp,
                        "requires_user_choice": routing_intent.requires_user_choice,
                        "underspecification_kind": routing_intent.underspecification_kind,
                        "candidate_capabilities": routing_intent.candidate_capabilities,
                        "reasoning": routing_intent.reasoning,
                    }
                ),
                error=classification.error,
            )
        elif requires_review != classification.requires_review or status != classification.status:
            classification = IntentTaskResult(
                task_id=classification.task_id,
                agent_role=classification.agent_role,
                status=status,
                confidence=classification.confidence,
                requires_review=requires_review,
                output=classification.output,
                error=classification.error,
            )

        if routing_intent is not None:
            resolved_task_kind = routing_intent.task_kind
            candidate_capabilities = list(routing_intent.candidate_capabilities)
            requires_mcp = routing_intent.requires_mcp
        else:
            resolved_task_kind = (
                classification.output.task_kind if classification.output is not None else "clarification_needed"
            )
            candidate_capabilities = (
                list(classification.output.candidate_capabilities) if classification.output is not None else []
            )
            requires_mcp = classification.output.requires_mcp if classification.output is not None else False
        worker = getattr(execution, "agent_role", "none") if execution is not None else "none"
        await self._session_service.touch_session(
            thread_id=thread_id,
            context_patch={
                "last_operation": "classify",
                "last_task_id": resolved_task_id,
                "last_task_kind": resolved_task_kind,
                "candidate_capabilities": candidate_capabilities,
                "requires_mcp": requires_mcp,
                "last_status": classification.status,
                "requires_review": classification.requires_review,
                "worker": worker,
                "escalation_reason": escalation_reason,
            },
            status="needs_review" if classification.requires_review else "active",
        )
        await _write_audit(
            conversation_id=thread_id,
            event="intent_classify_completed",
            metadata={
                "status": classification.status,
                "task_kind": resolved_task_kind,
                "worker": worker,
                "requires_review": str(classification.requires_review),
            },
        )
        return classification

    @traceable(name="intent_service.process")
    async def process(
        self,
        text: str,
        thread_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        *,
        is_admin: bool = False,
        attachment_ids: Sequence[UUID] | None = None,
    ) -> FormatterTaskResult:
        """Возвращает финальный отформатированный ответ платформы."""
        started = perf_counter()
        resolved_task_id = task_id or str(uuid4())
        logger.info(
            "agent.turn.start",
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id or "",
            text_chars=len(text),
        )
        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=True,
        )
        await self._kill_switch.assert_clear(conversation_id=thread_id)
        tenant_key = _tenant_budget_key(user_id=user_id, org_id=org_id, thread_id=thread_id)
        await self._cost_budget.assert_daily_allows_turn(tenant_key=tenant_key)
        resolved_attachments = await self._resolve_turn_attachment_ids(
            attachment_ids,
            thread_id=thread_id,
            restore_pending=True,
        )
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            title=_derive_session_title(text),
            context_patch={
                "last_operation": "process",
                "last_task_id": resolved_task_id,
                "last_user_text": session_user_text_preview(text),
                "org_id": org_id or "",
                **self._attachment_context_patch(resolved_attachments),
            },
        )
        if self._dialog_turn_store is not None:
            await self._dialog_turn_store.append_turn(
                thread_id=thread_id,
                role="user",
                content=text,
                task_id=resolved_task_id,
            )

        final_state = await self._graph_runner.run_graph(
            text=text,
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=tenant_key,
            untrusted_context=await self._turn_untrusted_context(
                resolved_attachments,
                thread_id=thread_id,
                user_id=user_id,
            ),
        )
        interrupted = _extract_interrupt(final_state)
        if interrupted is not None:
            formatted = await self._hitl_flow.finalize_tool_interrupt(
                interrupt_payload=interrupted,
                thread_id=thread_id,
                task_id=resolved_task_id,
                user_id=user_id,
                org_id=org_id,
            )
        else:
            formatted = await self._graph_runner.finalize_formatted_state(
                final_state,
                text=text,
                thread_id=thread_id,
                task_id=resolved_task_id,
                user_id=user_id,
                org_id=org_id,
                operation="process",
            )
        await self._after_process_metrics_and_cache(
            final_state=final_state if interrupted is None else None,
            formatted=formatted,
            text=text,
            tenant_key=tenant_key,
            started=started,
            skip_cache=bool(resolved_attachments),
        )
        return formatted

    async def _resolve_response_locale(self, *, thread_id: str, user_text: str) -> str:
        session = await self._session_service.get_session(thread_id=thread_id)
        prior_locale: str | None = None
        ui_locale: str | None = None
        if session is not None and isinstance(session.context, dict):
            prior_raw = session.context.get("response_locale")
            ui_raw = session.context.get("ui_locale")
            prior_locale = prior_raw if isinstance(prior_raw, str) else None
            ui_locale = ui_raw if isinstance(ui_raw, str) else None
        return ReplyLocalePolicy.resolve(
            user_text=user_text,
            prior_locale=prior_locale,
            ui_locale=ui_locale,
        )

    async def _after_process_metrics_and_cache(
        self,
        *,
        final_state: AgentGraphState | None,
        formatted: FormatterTaskResult,
        text: str,
        tenant_key: str,
        started: float,
        skip_cache: bool,
    ) -> None:
        from palatium_ai.application.orchestration import selectors as orch_selectors

        task_kind = "unknown"
        strategy = "unknown"
        locale = "und"
        if final_state is not None:
            routing = final_state.get("routing_intent")
            if routing is not None:
                task_kind = str(getattr(routing, "task_kind", "") or "unknown")
            strategy = str(orch_selectors.selected_strategy(final_state))
            locale = str(final_state.get("response_locale") or "und")
        elif formatted.output is not None:
            locale = formatted.output.locale or "und"
        agent_metrics.record_turn_duration(
            task_kind=task_kind,
            strategy=strategy,
            duration_seconds=perf_counter() - started,
        )
        if skip_cache or final_state is None:
            return
        await self._response_cache.put_if_cacheable(
            tenant_key=tenant_key,
            user_text=text,
            locale=locale,
            strategy=strategy,
            result=formatted,
        )

    @traceable(name="intent_service.process_stream")
    async def process_stream(
        self,
        text: str,
        thread_id: str,
        task_id: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
        *,
        is_admin: bool = False,
        attachment_ids: Sequence[UUID] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """SSE-oriented process: yield hop events, then a final FormatterTaskResult payload."""
        started = perf_counter()
        resolved_task_id = task_id or str(uuid4())
        logger.info(
            "agent.turn.start",
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id or "",
            text_chars=len(text),
            stream=True,
        )
        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=True,
        )
        await self._kill_switch.assert_clear(conversation_id=thread_id)
        tenant_key = _tenant_budget_key(user_id=user_id, org_id=org_id, thread_id=thread_id)
        await self._cost_budget.assert_daily_allows_turn(tenant_key=tenant_key)
        resolved_attachments = await self._resolve_turn_attachment_ids(
            attachment_ids,
            thread_id=thread_id,
            restore_pending=True,
        )
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            title=_derive_session_title(text),
            context_patch={
                "last_operation": "process_stream",
                "last_task_id": resolved_task_id,
                "last_user_text": session_user_text_preview(text),
                "org_id": org_id or "",
                **self._attachment_context_patch(resolved_attachments),
            },
        )
        if self._dialog_turn_store is not None:
            await self._dialog_turn_store.append_turn(
                thread_id=thread_id,
                role="user",
                content=text,
                task_id=resolved_task_id,
            )

        untrusted = await self._turn_untrusted_context(
            resolved_attachments,
            thread_id=thread_id,
            user_id=user_id,
        )
        final_state: AgentGraphState | None = None
        async for event in self._graph_runner.stream_graph(
            text=text,
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=tenant_key,
            untrusted_context=untrusted,
        ):
            if event.get("event") == "final_state":
                final_state = cast("AgentGraphState", event["state"])
                continue
            yield event

        if final_state is None:
            yield {
                "event": "error",
                "message": "Graph stream ended without final state",
                "task_id": resolved_task_id,
                "thread_id": thread_id,
            }
            return

        interrupted = _extract_interrupt(final_state)
        if interrupted is not None:
            formatted = await self._hitl_flow.finalize_tool_interrupt(
                interrupt_payload=interrupted,
                thread_id=thread_id,
                task_id=resolved_task_id,
                user_id=user_id,
                org_id=org_id,
            )
        else:
            formatted = await self._graph_runner.finalize_formatted_state(
                final_state,
                text=text,
                thread_id=thread_id,
                task_id=resolved_task_id,
                user_id=user_id,
                org_id=org_id,
                operation="process_stream",
            )
        await self._after_process_metrics_and_cache(
            final_state=final_state if interrupted is None else None,
            formatted=formatted,
            text=text,
            tenant_key=tenant_key,
            started=started,
            skip_cache=bool(resolved_attachments),
        )
        yield {
            "event": "result",
            "task_id": resolved_task_id,
            "thread_id": thread_id,
            "result": formatted.model_dump(mode="json"),
        }

    @traceable(name="intent_service.process_hitl_choice")
    async def process_hitl_choice(
        self,
        *,
        thread_id: str,
        action_id: str,
        card: HITLCardView,
        user_id: str | None = None,
        org_id: str | None = None,
        is_admin: bool = False,
    ) -> FormatterTaskResult:
        """Resume after user_choice: action_id-bound text, never raw option.label as intent."""
        return await self._hitl_flow.process_hitl_choice(
            thread_id=thread_id,
            action_id=action_id,
            card=card,
            user_id=user_id,
            org_id=org_id,
            is_admin=is_admin,
        )

    @traceable(name="intent_service.acknowledge_quality_approve")
    async def acknowledge_quality_approve(
        self,
        *,
        thread_id: str,
        user_id: str | None = None,
        is_admin: bool = False,
        content_sha256: str | None = None,
    ) -> None:
        """Approve quality HITL: keep answer, clear revision counters, record content digest."""
        return await self._hitl_flow.acknowledge_quality_approve(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            content_sha256=content_sha256,
        )

    @traceable(name="intent_service.revise_after_quality_reject")
    async def revise_after_quality_reject(
        self,
        *,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
        is_admin: bool = False,
    ) -> FormatterTaskResult:
        """Re-run graph with critic/human reject feedback (no new user turn)."""
        return await self._hitl_flow.revise_after_quality_reject(
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            org_id=org_id,
            is_admin=is_admin,
        )

    async def resume_after_tool_approval(
        self,
        *,
        thread_id: str,
        task_id: str,
        action_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
        is_admin: bool = False,
    ) -> FormatterTaskResult | None:
        """Resume a graph paused on mcp_tool_approval after HITL resolve."""
        return await self._hitl_flow.resume_after_tool_approval(
            thread_id=thread_id,
            task_id=task_id,
            action_id=action_id,
            user_id=user_id,
            org_id=org_id,
            is_admin=is_admin,
        )

    async def deny_tool_interrupt(
        self,
        *,
        thread_id: str,
        task_id: str,
        card_id: str,
        reason: str,
    ) -> None:
        """HitlDenyResumePort: clear open tool-approval interrupt with reject."""
        await self._hitl_flow.system_deny_tool_interrupt(
            thread_id=thread_id,
            task_id=task_id,
            card_id=card_id,
            reason=reason,
        )
