# src/palatium_ai/application/services/intent_service.py

"""Use case: классификация намерения через LangGraph + dialog memory."""

from __future__ import annotations

from datetime import UTC
from typing import TYPE_CHECKING, Literal, cast

from langgraph.types import Command

from palatium_ai.application.orchestration.run_config import build_graph_run_config
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.cost_budget import CostBudgetService
from palatium_ai.application.services.kill_switch import KillSwitchService
from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.hop_timings import turn_hop_timings
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.observability.turn_tokens import turn_token_usage
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock, ParagraphBlock
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.sessions.context_privacy import session_user_text_preview

_DEFAULT_DIALOG_WINDOW = 12
_MAX_QUALITY_REVISIONS = 2

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.application.services.session_service import SessionService
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort

logger = get_logger(__name__)


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
        consolidation: MemoryConsolidationService | None = None,
        dialog_window_size: int = _DEFAULT_DIALOG_WINDOW,
        recall_min_confidence: float = 0.7,
        recall_max_items: int = 4,
        recall_max_chars: int = 800,
        contextualizer_dialog_max_chars: int = 6000,
        worker_summary_max_chars: int = 4000,
        mcp_tool_output_max_chars: int = 3000,
        turn_hop_budget_ms: int = 15_000,
    ) -> None:
        self._graph = graph
        self._session_service = session_service
        self._hitl_service = hitl_service
        self._kill_switch = kill_switch or KillSwitchService()
        self._cost_budget = cost_budget or CostBudgetService()
        self._dialog_turn_store = dialog_turn_store
        self._memory_port = memory_port
        self._consolidation = consolidation
        self._dialog_window_size = dialog_window_size
        self._recall_min_confidence = recall_min_confidence
        self._recall_max_items = recall_max_items
        self._recall_max_chars = recall_max_chars
        self._contextualizer_dialog_max_chars = contextualizer_dialog_max_chars
        self._worker_summary_max_chars = worker_summary_max_chars
        self._mcp_tool_output_max_chars = mcp_tool_output_max_chars
        self._turn_hop_budget_ms = turn_hop_budget_ms

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
    ) -> IntentTaskResult:
        """Возвращает platform-level классификацию задачи."""
        resolved_task_id = task_id or thread_id
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
        final_state = await self._run_graph(
            text=text,
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=_tenant_budget_key(user_id=user_id, org_id=org_id, thread_id=thread_id),
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
        if critic is not None:
            critic_requires_review = bool(getattr(critic, "requires_review", False))
            if critic_requires_review:
                requires_review = True
                escalation_reason = "critic_requires_review"
                if status == "success":
                    status = "partial"
                agent_metrics.record_human_escalation("critic_requires_review")

        if requires_review != classification.requires_review or status != classification.status:
            classification = IntentTaskResult(
                task_id=classification.task_id,
                agent_role=classification.agent_role,
                status=status,
                confidence=classification.confidence,
                requires_review=requires_review,
                output=classification.output,
                error=classification.error,
            )

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
    ) -> FormatterTaskResult:
        """Возвращает финальный отформатированный ответ платформы."""
        resolved_task_id = task_id or thread_id
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
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            title=_derive_session_title(text),
            context_patch={
                "last_operation": "process",
                "last_task_id": resolved_task_id,
                "last_user_text": session_user_text_preview(text),
                "org_id": org_id or "",
            },
        )
        if self._dialog_turn_store is not None:
            await self._dialog_turn_store.append_turn(
                thread_id=thread_id,
                role="user",
                content=text,
                task_id=resolved_task_id,
            )

        final_state = await self._run_graph(
            text=text,
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=tenant_key,
        )
        interrupted = _extract_interrupt(final_state)
        if interrupted is not None:
            return await self._finalize_tool_interrupt(
                interrupt_payload=interrupted,
                thread_id=thread_id,
                task_id=resolved_task_id,
                user_id=user_id,
                org_id=org_id,
            )

        return await self._finalize_formatted_state(
            final_state,
            text=text,
            thread_id=thread_id,
            task_id=resolved_task_id,
            user_id=user_id,
            org_id=org_id,
            operation="process",
        )

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
        from palatium_ai.domain.hitl.choice_resume import ChoiceResumePolicy

        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=False,
        )
        selection = ChoiceResumePolicy.selection_from_card(card, action_id)
        safe_text = ChoiceResumePolicy.graph_user_text(selection)
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            context_patch={
                "hitl_resume_kind": selection.resume_kind,
                "hitl_action_id": selection.action_id,
                "last_operation": "hitl_choice",
            },
            status="active",
        )
        return await self.process(
            text=safe_text,
            thread_id=thread_id,
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
        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=False,
        )
        digest = (content_sha256 or "").strip()
        context_patch: dict[str, object] = {
            "last_operation": "quality_approve",
            "requires_review": False,
            "quality_revision_count": "0",
        }
        if digest:
            context_patch["approved_content_sha256"] = digest[:64]
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            context_patch=context_patch,
            status="active",
        )
        await _write_audit(
            conversation_id=thread_id,
            event="quality_hitl_approved",
            metadata={"content_sha256": digest[:64]} if digest else {},
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
        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=False,
        )
        await self._kill_switch.assert_clear(conversation_id=thread_id)
        session = await self._session_service.get_session(thread_id=thread_id)
        context = dict(session.context) if session is not None and isinstance(session.context, dict) else {}
        text = await self._resolve_revision_user_text(thread_id=thread_id, context=context)
        if not text:
            return FormatterTaskResult(
                task_id=task_id,
                agent_role="formatter",
                status="failure",
                confidence=0.0,
                requires_review=False,
                output=None,
                error="Cannot revise: no stored user text for this thread",
            )

        try:
            revision_count = int(str(context.get("quality_revision_count") or "0"))
        except ValueError:
            revision_count = 0
        if revision_count >= _MAX_QUALITY_REVISIONS:
            return FormatterTaskResult(
                task_id=task_id,
                agent_role="formatter",
                status="failure",
                confidence=0.0,
                requires_review=False,
                output=None,
                error=f"Quality revision limit reached ({_MAX_QUALITY_REVISIONS})",
            )

        critic_summary = str(context.get("last_critic_summary") or "").strip()
        feedback = critic_summary or (
            "Human rejected the previous answer. Produce a corrected response using "
            "dialog sources; do not claim missing source text when prior user content exists."
        )
        tenant_key = _tenant_budget_key(user_id=user_id, org_id=org_id, thread_id=thread_id)
        await self._cost_budget.assert_daily_allows_turn(tenant_key=tenant_key)
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            context_patch={
                "last_operation": "quality_revise",
                "quality_revision_count": str(revision_count + 1),
            },
        )

        revision_task_id = f"{task_id}-rev{revision_count + 1}"
        final_state = await self._run_graph(
            text=text,
            thread_id=thread_id,
            task_id=revision_task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=tenant_key,
            revision_feedback=feedback,
            exclude_trailing_user=False,
        )
        interrupted = _extract_interrupt(final_state)
        if interrupted is not None:
            return await self._finalize_tool_interrupt(
                interrupt_payload=interrupted,
                thread_id=thread_id,
                task_id=revision_task_id,
                user_id=user_id,
                org_id=org_id,
            )
        return await self._finalize_formatted_state(
            final_state,
            text=text,
            thread_id=thread_id,
            task_id=revision_task_id,
            user_id=user_id,
            org_id=org_id,
            operation="quality_revise",
        )

    async def _finalize_formatted_state(
        self,
        final_state: AgentGraphState,
        *,
        text: str,
        thread_id: str,
        task_id: str,
        user_id: str | None,
        org_id: str | None,
        operation: str,
    ) -> FormatterTaskResult:
        """Attach HITL, persist assistant turn, update session after a graph run."""
        formatted = final_state.get("formatted")
        classification = final_state.get("classification")
        routing_intent = final_state.get("routing_intent")
        if routing_intent is not None:
            resolved_task_kind = routing_intent.task_kind
        elif isinstance(classification, IntentTaskResult) and classification.output is not None:
            resolved_task_kind = classification.output.task_kind
        else:
            resolved_task_kind = "clarification_needed"

        critic = final_state.get("critic")
        critic_summary = ""
        if critic is not None and critic.output is not None:
            critic_summary = critic.output.summary.strip()[:2000]

        from palatium_ai.application.orchestration import selectors as orch_selectors

        selected_strategy = orch_selectors.selected_strategy(final_state)
        resolved_requires_user_choice = bool(
            getattr(routing_intent, "requires_user_choice", False)
        ) if routing_intent is not None else False

        if isinstance(formatted, FormatterTaskResult):
            formatted = await self._attach_hitl_cards(
                formatted,
                thread_id=thread_id,
                task_id=task_id,
                selected_strategy=selected_strategy,
                task_kind=resolved_task_kind,
                requires_user_choice=resolved_requires_user_choice,
                user_id=user_id,
                org_id=org_id,
            )
            if self._dialog_turn_store is not None:
                await self._dialog_turn_store.append_turn(
                    thread_id=thread_id,
                    role="assistant",
                    content=_assistant_turn_content(formatted),
                    task_id=task_id,
                    payload=_assistant_turn_payload(formatted),
                )
            await self._session_service.touch_session(
                thread_id=thread_id,
                user_id=user_id,
                context_patch={
                    "last_operation": operation,
                    "last_task_id": task_id,
                    "last_task_kind": resolved_task_kind,
                    "last_status": formatted.status,
                    "requires_review": formatted.requires_review,
                    "last_response_preview": _response_preview(formatted),
                    "hitl_card_ids": ",".join(card.card_id for card in formatted.hitl_cards),
                    "effective_user_text": session_user_text_preview(
                        str(final_state.get("effective_user_text") or text)
                    ),
                    "last_critic_summary": critic_summary,
                },
                status="needs_review" if formatted.requires_review else "active",
            )
            await _write_audit(
                conversation_id=thread_id,
                event="intent_process_completed",
                metadata={
                    "status": formatted.status,
                    "task_kind": resolved_task_kind,
                    "requires_review": str(formatted.requires_review),
                    "hitl_cards": str(len(formatted.hitl_cards)),
                    "operation": operation,
                },
            )
            if self._consolidation is not None and formatted.status == "success" and not formatted.requires_review:
                self._consolidation.enqueue(
                    thread_id=thread_id,
                    task_id=task_id,
                    user_id=user_id,
                    org_id=org_id,
                )
            return formatted

        failure_result = FormatterTaskResult(
            task_id=task_id,
            agent_role="formatter",
            status="failure",
            confidence=0.0,
            requires_review=True,
            output=None,
            error="Graph did not produce formatted result",
        )
        await self._session_service.touch_session(
            thread_id=thread_id,
            context_patch={
                "last_operation": operation,
                "last_task_id": task_id,
                "last_task_kind": resolved_task_kind,
                "last_status": failure_result.status,
                "requires_review": failure_result.requires_review,
                "last_error": failure_result.error or "",
            },
            status="needs_review",
        )
        return failure_result

    async def _run_graph(
        self,
        *,
        text: str,
        thread_id: str,
        task_id: str,
        user_id: str | None = None,
        org_id: str | None = None,
        tenant_key: str | None = None,
        revision_feedback: str | None = None,
        exclude_trailing_user: bool = True,
    ) -> AgentGraphState:
        """Запускает LangGraph с dialog window + thread checkpointer config."""
        dialog_window = await self._load_dialog_window(thread_id=thread_id)
        # Exclude the user turn just appended (Contextualizer sees prior only).
        if exclude_trailing_user and dialog_window.turns and dialog_window.turns[-1].role == "user":
            prior_turns = dialog_window.turns[:-1]
        else:
            prior_turns = dialog_window.turns
        prior_window = DialogTurnWindow(
            thread_id=thread_id,
            turns=prior_turns,
            limit=dialog_window.limit,
        )
        memory_recall = await recall_for_thread(
            self._memory_port,
            thread_id=thread_id,
            query=text,
            user_id=user_id,
            org_id=org_id,
            limit=self._recall_max_items,
            max_chars=self._recall_max_chars,
            min_confidence=self._recall_min_confidence,
        )
        prompt_budget = MemoryPromptBudget(
            dialog_max_chars=self._contextualizer_dialog_max_chars,
            memory_max_items=self._recall_max_items,
            memory_max_chars=self._recall_max_chars,
            worker_summary_max_chars=self._worker_summary_max_chars,
            mcp_tool_output_max_chars=self._mcp_tool_output_max_chars,
        )
        with turn_hop_timings() as hops, turn_token_usage() as tokens:
            graph_input: AgentGraphState = {
                "task_id": task_id,
                "user_text": text,
                "thread_id": thread_id,
                "dialog_window": prior_window,
                "memory_recall": memory_recall,
                "prompt_budget": prompt_budget,
            }
            if revision_feedback and revision_feedback.strip():
                graph_input["revision_feedback"] = revision_feedback.strip()[:4_000]
            final_state = cast(
                "AgentGraphState",
                await self._graph.ainvoke(
                    graph_input,
                    config=build_graph_run_config(thread_id=thread_id, task_id=task_id),
                ),
            )
            hop_fields = hops.budget_status(self._turn_hop_budget_ms)
            token_fields = tokens.as_log_fields()
            logger.info(
                "agent.turn.hops",
                thread_id=thread_id,
                task_id=task_id,
                **hop_fields,
                **token_fields,
            )
            if hop_fields["hop_budget_exceeded"]:
                agent_metrics.record_turn_hop_budget_exceeded()
                logger.warning(
                    "agent.turn.slow",
                    thread_id=thread_id,
                    task_id=task_id,
                    hop_slowest_node=hop_fields["hop_slowest_node"],
                    hop_slowest_ms=hop_fields["hop_slowest_ms"],
                    hop_total_ms=hop_fields["hop_total_ms"],
                    hop_budget_ms=hop_fields["hop_budget_ms"],
                )
            if tenant_key is not None:
                cost = sum(item.cost_usd for item in tokens.usages)
                await self._cost_budget.record_turn_cost(tenant_key=tenant_key, cost_usd=cost)
        return final_state

    async def _load_dialog_window(self, *, thread_id: str) -> DialogTurnWindow:
        if self._dialog_turn_store is None:
            return DialogTurnWindow(thread_id=thread_id, turns=(), limit=self._dialog_window_size)
        return await self._dialog_turn_store.list_recent_turns(
            thread_id=thread_id,
            limit=self._dialog_window_size,
        )

    async def _resolve_revision_user_text(self, *, thread_id: str, context: dict[str, object]) -> str:
        """Authoritative user text for quality revise: dialog turns, then session preview fallback."""
        window = await self._load_dialog_window(thread_id=thread_id)
        from_dialog = window.latest_user_content()
        if from_dialog:
            return from_dialog
        return str(context.get("effective_user_text") or context.get("last_user_text") or "").strip()

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
        """Resume a graph paused on mcp_tool_approval after HITL resolve.

        Returns ``None`` when the checkpoint has no pending interrupt (e.g. a
        minted approval card with no Researcher pause) — resolve still stands.
        """
        await self._session_service.assert_thread_access(
            thread_id=thread_id,
            user_id=user_id,
            is_admin=is_admin,
            allow_missing=False,
        )
        await self._kill_switch.assert_clear(conversation_id=thread_id)
        config = build_graph_run_config(thread_id=thread_id, task_id=task_id)
        try:
            snapshot = await self._graph.aget_state(config)
        except ValueError as exc:
            # Missing checkpoint_ns / no prior interrupt for this task — resolve stands alone.
            logger.info(
                "agent.turn.resume_skipped",
                thread_id=thread_id,
                task_id=task_id,
                action_id=action_id,
                reason="checkpoint_unavailable",
                detail=str(exc),
            )
            return None
        if not _snapshot_awaits_resume(snapshot):
            logger.info(
                "agent.turn.resume_skipped",
                thread_id=thread_id,
                task_id=task_id,
                action_id=action_id,
                reason="no_pending_interrupt",
            )
            return None
        with turn_hop_timings() as hops, turn_token_usage() as tokens:
            final_state = cast(
                "AgentGraphState",
                await self._graph.ainvoke(
                    Command(resume={"action_id": action_id}),
                    config=config,
                ),
            )
            hop_fields = hops.budget_status(self._turn_hop_budget_ms)
            token_fields = tokens.as_log_fields()
            logger.info(
                "agent.turn.hops",
                thread_id=thread_id,
                task_id=task_id,
                resume=True,
                **hop_fields,
                **token_fields,
            )

        interrupted = _extract_interrupt(final_state)
        if interrupted is not None:
            return await self._finalize_tool_interrupt(
                interrupt_payload=interrupted,
                thread_id=thread_id,
                task_id=task_id,
                user_id=user_id,
                org_id=org_id,
            )

        formatted = final_state.get("formatted")
        if not isinstance(formatted, FormatterTaskResult):
            return FormatterTaskResult(
                task_id=task_id,
                agent_role="formatter",
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=None,
                error="Graph resume did not produce formatted result",
            )

        formatted = await self._attach_hitl_cards(
            formatted,
            thread_id=thread_id,
            task_id=task_id,
            user_id=user_id,
            org_id=org_id,
        )
        if self._dialog_turn_store is not None:
            await self._dialog_turn_store.append_turn(
                thread_id=thread_id,
                role="assistant",
                content=_assistant_turn_content(formatted),
                task_id=task_id,
                payload=_assistant_turn_payload(formatted),
            )
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            context_patch={
                "last_operation": "process_resume",
                "last_task_id": task_id,
                "last_status": formatted.status,
                "requires_review": formatted.requires_review,
                "last_response_preview": _response_preview(formatted),
                "hitl_card_ids": ",".join(card.card_id for card in formatted.hitl_cards),
                "pending_tool_approval": "",
            },
            status="needs_review" if formatted.requires_review else "active",
        )
        await _write_audit(
            conversation_id=thread_id,
            event="intent_process_resumed",
            metadata={
                "status": formatted.status,
                "action_id": action_id,
                "requires_review": str(formatted.requires_review),
            },
        )
        if self._consolidation is not None and formatted.status == "success" and not formatted.requires_review:
            self._consolidation.enqueue(
                thread_id=thread_id,
                task_id=task_id,
                user_id=user_id,
                org_id=org_id,
            )
        return formatted

    async def _finalize_tool_interrupt(
        self,
        *,
        interrupt_payload: dict[str, object],
        thread_id: str,
        task_id: str,
        user_id: str | None,
        org_id: str | None = None,
    ) -> FormatterTaskResult:
        """Create MCP tool-approval HITL card and return a paused turn response."""
        server_name = str(interrupt_payload.get("server_name") or "unknown")
        tool_name = str(interrupt_payload.get("tool_name") or "unknown")
        side_effect = str(interrupt_payload.get("side_effect") or "unknown")
        risk_tier = str(interrupt_payload.get("risk_tier") or "medium")
        arguments = interrupt_payload.get("arguments")
        preview = _argument_preview(arguments)
        tier_literal: Literal["low", "medium", "high"]
        if risk_tier in {"low", "medium", "high"}:
            tier_literal = cast("Literal['low', 'medium', 'high']", risk_tier)
        else:
            tier_literal = "medium"
        card = await self._hitl_service.create_tool_approval_card(
            thread_id=thread_id,
            task_id=task_id,
            server_name=server_name,
            tool_name=tool_name,
            side_effect=side_effect,
            risk_score=risk_score_for_tier(tier_literal),
            argument_preview=preview,
            owner_user_id=user_id,
            org_id=org_id,
        )
        document = ContentDocument(
            locale="en",
            title="Tool approval required",
            blocks=(
                HeadingBlock(level=2, text="Human approval required before tool call", icon="shield"),
                ParagraphBlock(
                    text=(
                        f"Paused before MCP `{server_name}.{tool_name}` "
                        f"(side_effect={side_effect}). Choose Allow or Deny."
                    )
                ),
            ),
            meta=DocumentMeta(confidence=0.0, requires_review=True, source_refs=()),
        )
        result = FormatterTaskResult(
            task_id=task_id,
            agent_role="formatter",
            status="partial",
            confidence=0.0,
            requires_review=True,
            output=document,
            hitl_cards=(card,),
            error=None,
        )
        if self._dialog_turn_store is not None:
            await self._dialog_turn_store.append_turn(
                thread_id=thread_id,
                role="assistant",
                content=_assistant_turn_content(result),
                task_id=task_id,
                payload=_assistant_turn_payload(result),
            )
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            context_patch={
                "last_operation": "process",
                "last_task_id": task_id,
                "last_status": "partial",
                "requires_review": True,
                "pending_tool_approval": "1",
                "hitl_card_ids": card.card_id,
                "last_response_preview": _response_preview(result),
            },
            status="needs_review",
        )
        await _write_audit(
            conversation_id=thread_id,
            event="mcp_tool_interrupt",
            metadata={
                "server_name": server_name,
                "tool_name": tool_name,
                "side_effect": side_effect,
                "card_id": card.card_id,
            },
        )
        return result

    async def _attach_hitl_cards(
        self,
        formatted: FormatterTaskResult,
        *,
        thread_id: str,
        task_id: str,
        selected_strategy: str | None = None,
        task_kind: str | None = None,
        requires_user_choice: bool = False,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> FormatterTaskResult:
        """Сервер создаёт HITL-карточки; LLM actions не являются источником истины."""
        from palatium_ai.application.services.interaction_assembler import (
            InteractionAssembler,
            interaction_plan_log_fields,
        )
        from palatium_ai.domain.content import parse_content_document

        if formatted.output is None and not formatted.requires_review:
            return formatted.model_copy(update={"hitl_cards": ()})

        document = formatted.output
        if document is not None:
            # Heal degraded block types after LangGraph/checkpointer serde.
            document = parse_content_document(document.model_dump(mode="json"))
            formatted = formatted.model_copy(update={"output": document})

        strategy = (
            selected_strategy.value
            if selected_strategy is not None and hasattr(selected_strategy, "value")
            else selected_strategy
        )
        assembled = InteractionAssembler.assemble(
            document,
            requires_review=formatted.requires_review,
            selected_strategy=strategy if isinstance(strategy, str) else None,
            task_kind=task_kind,
            requires_user_choice=requires_user_choice,
        )
        logger.info(
            "hitl.interaction_plan",
            thread_id=thread_id,
            task_id=task_id,
            task_kind=task_kind,
            selected_strategy=strategy,
            requires_user_choice=requires_user_choice,
            **interaction_plan_log_fields(assembled),
        )
        if assembled.invalid:
            agent_metrics.record_hitl_deny("formatter_output_invalid")
            await _write_audit(
                conversation_id=thread_id,
                event="hitl_formatter_output_invalid",
                metadata={
                    "task_id": task_id,
                    "task_kind": task_kind or "",
                    "selected_strategy": str(strategy or ""),
                    "menu_shaped": str(assembled.plan.menu_shaped),
                    "promoted_from": assembled.plan.promoted_from,
                    "force_structural": str(assembled.plan.force_structural),
                },
            )
            return formatted.model_copy(
                update={
                    "status": "failure",
                    "error": "formatter_output_invalid",
                    "requires_review": True,
                    "hitl_cards": (),
                    "confidence": min(formatted.confidence, 0.0),
                }
            )

        plan = assembled.plan
        document = assembled.document
        cards: list[HITLCardView] = []

        if plan.choice_actions and document is not None:
            choice = await self._hitl_service.create_choice_card(
                thread_id=thread_id,
                task_id=task_id,
                title=document.title or "Choose an option",
                body=None,
                actions=plan.choice_actions,
                owner_user_id=user_id,
                org_id=org_id,
            )
            cards.append(choice)

        if plan.mint_quality_review and document is not None:
            cards.append(
                await self._hitl_service.create_review_card(
                    thread_id=thread_id,
                    task_id=task_id,
                    document=document,
                    confidence=formatted.confidence,
                    owner_user_id=user_id,
                    org_id=org_id,
                )
            )

        if document is None:
            return formatted.model_copy(update={"hitl_cards": tuple(cards)})

        return formatted.model_copy(
            update={
                "output": document,
                "hitl_cards": tuple(cards),
            }
        )


async def _write_audit(*, conversation_id: str, event: str, metadata: dict[str, str]) -> None:
    from datetime import datetime

    logger = get_audit_logger()
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    await logger.append_async(
        timestamp=timestamp,
        conversation_id=conversation_id,
        event=event,
        metadata=metadata,
    )


def _tenant_budget_key(*, user_id: str | None, org_id: str | None, thread_id: str) -> str:
    """Stable tenant key for daily cost accounting."""
    if user_id and user_id.strip():
        return user_id.strip()
    if org_id and org_id.strip():
        return f"org:{org_id.strip()}"
    return f"thread:{thread_id}"


def _derive_session_title(text: str) -> str:
    """Build a stable human-readable title from the first user utterance."""
    normalized = " ".join(text.split())
    return normalized[:80] if normalized else "Untitled session"


def _response_preview(result: FormatterTaskResult) -> str:
    """Return a short preview of the latest formatted response for session context."""
    if result.output is None:
        return result.error or ""
    return result.output.preview_text(200)


def _assistant_turn_content(result: FormatterTaskResult) -> str:
    """Persist flattened assistant body for Contextualizer (not title-only preview)."""
    if result.output is None:
        return result.error or "(empty assistant response)"
    return result.output.plain_text(4000)


def _assistant_turn_payload(result: FormatterTaskResult) -> dict[str, object] | None:
    """Persist document + HITL card ids/meta for hydrate — never capability tokens."""
    from palatium_ai.domain.hitl.choice_resume import hitl_card_public_dump

    if result.output is None and not result.hitl_cards:
        return None
    return {
        "schema": "assistant_turn_v1",
        "document": result.output.model_dump(mode="json") if result.output is not None else None,
        "hitl_cards": [hitl_card_public_dump(card) for card in result.hitl_cards],
    }


def _snapshot_awaits_resume(snapshot: object) -> bool:
    """Return whether checkpointer awaits Command(resume=...) for a tool interrupt."""
    interrupts = getattr(snapshot, "interrupts", None) or ()
    if interrupts:
        return True
    tasks = getattr(snapshot, "tasks", None) or ()
    for task in tasks:
        task_interrupts = getattr(task, "interrupts", None) or ()
        if task_interrupts:
            return True
    values = getattr(snapshot, "values", None)
    return bool(isinstance(values, dict) and values.get("__interrupt__"))


def _extract_interrupt(state: object) -> dict[str, object] | None:
    """Read LangGraph `__interrupt__` payload when a node called interrupt()."""
    if not isinstance(state, dict):
        return None
    raw = state.get("__interrupt__")
    if not raw:
        return None
    items = raw if isinstance(raw, (list, tuple)) else (raw,)
    first = items[0] if items else None
    value = getattr(first, "value", first)
    if isinstance(value, dict):
        return {str(key): item for key, item in value.items()}
    return None


def _argument_preview(arguments: object) -> str:
    if not isinstance(arguments, dict):
        return ""
    parts: list[str] = []
    for key, value in list(arguments.items())[:8]:
        parts.append(f"{key}={value!r}")
    return ", ".join(parts)
