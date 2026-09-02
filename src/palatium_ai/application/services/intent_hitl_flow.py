# src/palatium_ai/application/services/intent_hitl_flow.py

"""HITL choice / quality / tool-approval flows for IntentService."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Literal, cast

from langgraph.types import Command

from palatium_ai.application.orchestration.run_config import build_graph_run_config
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.hitl_service import HitlInvalidActionError
from palatium_ai.application.services.intent_turn_helpers import (
    argument_preview,
    assistant_turn_content,
    assistant_turn_payload,
    extract_interrupt,
    response_preview,
    snapshot_awaits_resume,
    tenant_budget_key,
    write_audit,
)
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import turn_hop_timings
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.turn_tokens import turn_token_usage
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.content import ContentDocument, DocumentMeta, HeadingBlock, ParagraphBlock
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier

if TYPE_CHECKING:
    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.application.services.intent_graph_runner import IntentGraphRunner
    from palatium_ai.application.services.kill_switch import KillSwitchService
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.application.services.option_synthesizer import OptionSynthesizer
    from palatium_ai.application.services.session_service import SessionService
    from palatium_ai.domain.memory.ports import DialogTurnStore

logger = get_logger(__name__)

_MAX_QUALITY_REVISIONS = 2

ProcessTurn = Callable[..., Awaitable[FormatterTaskResult]]


class IntentHitlFlow:
    """Choice resume, quality approve/revise, tool-approval interrupt + resume."""

    def __init__(
        self,
        *,
        graph_runner: IntentGraphRunner,
        session_service: SessionService,
        hitl_service: HitlService,
        kill_switch: KillSwitchService,
        cost_budget: CostBudgetService,
        process_turn: ProcessTurn,
        dialog_turn_store: DialogTurnStore | None = None,
        consolidation: MemoryConsolidationService | None = None,
        option_synthesizer: OptionSynthesizer | None = None,
    ) -> None:
        self._graph_runner = graph_runner
        self._session_service = session_service
        self._hitl_service = hitl_service
        self._kill_switch = kill_switch
        self._cost_budget = cost_budget
        self._process_turn = process_turn
        self._dialog_turn_store = dialog_turn_store
        self._consolidation = consolidation
        self._option_synthesizer = option_synthesizer

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
        return await self._process_turn(
            text=safe_text,
            thread_id=thread_id,
            user_id=user_id,
            org_id=org_id,
            is_admin=is_admin,
        )

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
        await write_audit(
            conversation_id=thread_id,
            event="quality_hitl_approved",
            metadata={"content_sha256": digest[:64]} if digest else {},
        )

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
        text = await self._graph_runner.resolve_revision_user_text(thread_id=thread_id, context=context)
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
        budget_key = tenant_budget_key(user_id=user_id, org_id=org_id, thread_id=thread_id)
        await self._cost_budget.assert_daily_allows_turn(tenant_key=budget_key)
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            context_patch={
                "last_operation": "quality_revise",
                "quality_revision_count": str(revision_count + 1),
            },
        )

        revision_task_id = f"{task_id}-rev{revision_count + 1}"
        final_state = await self._graph_runner.run_graph(
            text=text,
            thread_id=thread_id,
            task_id=revision_task_id,
            user_id=user_id,
            org_id=org_id,
            tenant_key=budget_key,
            revision_feedback=feedback,
            exclude_trailing_user=False,
        )
        interrupted = extract_interrupt(final_state)
        if interrupted is not None:
            return await self.finalize_tool_interrupt(
                interrupt_payload=interrupted,
                thread_id=thread_id,
                task_id=revision_task_id,
                user_id=user_id,
                org_id=org_id,
            )
        return await self._graph_runner.finalize_formatted_state(
            final_state,
            text=text,
            thread_id=thread_id,
            task_id=revision_task_id,
            user_id=user_id,
            org_id=org_id,
            operation="quality_revise",
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
            snapshot = await self._graph_runner.graph.aget_state(config)
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
        if not snapshot_awaits_resume(snapshot):
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
                await self._graph_runner.graph.ainvoke(
                    Command(resume={"action_id": action_id}),
                    config=config,
                ),
            )
            hop_fields = hops.budget_status(self._graph_runner.turn_hop_budget_ms)
            token_fields = tokens.as_log_fields()
            logger.info(
                "agent.turn.hops",
                thread_id=thread_id,
                task_id=task_id,
                resume=True,
                **hop_fields,
                **token_fields,
            )

        interrupted = extract_interrupt(final_state)
        if interrupted is not None:
            return await self.finalize_tool_interrupt(
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

        formatted = await self.attach_hitl_cards(
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
                content=assistant_turn_content(formatted),
                task_id=task_id,
                payload=assistant_turn_payload(formatted),
            )
        await self._session_service.touch_session(
            thread_id=thread_id,
            user_id=user_id,
            context_patch={
                "last_operation": "process_resume",
                "last_task_id": task_id,
                "last_status": formatted.status,
                "requires_review": formatted.requires_review,
                "last_response_preview": response_preview(formatted),
                "hitl_card_ids": ",".join(card.card_id for card in formatted.hitl_cards),
                "pending_tool_approval": "",
            },
            status="needs_review" if formatted.requires_review else "active",
        )
        await write_audit(
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

    async def system_deny_tool_interrupt(
        self,
        *,
        thread_id: str,
        task_id: str,
        card_id: str,
        reason: str,
    ) -> None:
        """Best-effort Command(resume=reject) without ownership/kill-switch gates.

        Used after TTL auto-reject / dead_letter / resolve-then-resume failure so an
        mcp_tool_approval interrupt cannot hang while the card is already terminal.
        """
        config = build_graph_run_config(thread_id=thread_id, task_id=task_id)
        try:
            snapshot = await self._graph_runner.graph.aget_state(config)
        except ValueError as exc:
            logger.info(
                "agent.turn.system_deny_skipped",
                thread_id=thread_id,
                task_id=task_id,
                card_id=card_id,
                reason="checkpoint_unavailable",
                detail=str(exc),
            )
            return
        if not snapshot_awaits_resume(snapshot):
            logger.info(
                "agent.turn.system_deny_skipped",
                thread_id=thread_id,
                task_id=task_id,
                card_id=card_id,
                reason="no_pending_interrupt",
            )
            return
        await self._graph_runner.graph.ainvoke(
            Command(resume={"action_id": "reject"}),
            config=config,
        )
        await self._session_service.touch_session(
            thread_id=thread_id,
            context_patch={
                "last_operation": "system_deny_tool_interrupt",
                "last_task_id": task_id,
                "pending_tool_approval": "",
                "last_status": "auto_rejected",
            },
            status="needs_review",
        )
        await write_audit(
            conversation_id=thread_id,
            event="hitl_tool_interrupt_system_deny",
            metadata={
                "card_id": card_id,
                "task_id": task_id,
                "reason": reason[:256],
                "action_id": "reject",
            },
        )
        agent_metrics.record_human_escalation("hitl_tool_interrupt_system_deny")

    async def finalize_tool_interrupt(
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
        preview = argument_preview(arguments)
        tier_literal: Literal["low", "medium", "high"]
        if risk_tier in {"low", "medium", "high"}:
            tier_literal = cast("Literal['low', 'medium', 'high']", risk_tier)
        else:
            tier_literal = "medium"
        try:
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
        except HitlInvalidActionError as exc:
            logger.warning(
                "agent.turn.tool_approval_refused",
                thread_id=thread_id,
                task_id=task_id,
                server=server_name,
                tool=tool_name,
                reason=str(exc),
            )
            return FormatterTaskResult(
                task_id=task_id,
                agent_role="formatter",
                status="failure",
                confidence=0.0,
                requires_review=True,
                output=ContentDocument(
                    locale="en",
                    title="Tool approval unavailable",
                    blocks=(
                        HeadingBlock(level=2, text="Cannot open tool approval", icon="shield"),
                        ParagraphBlock(
                            text=(
                                "High-risk MCP tool call was blocked because the session "
                                "has no org_id for manager escalation. Tool was not executed."
                            )
                        ),
                    ),
                    meta=DocumentMeta(confidence=0.0, requires_review=True, source_refs=()),
                ),
                hitl_cards=(),
                error=str(exc),
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
                content=assistant_turn_content(result),
                task_id=task_id,
                payload=assistant_turn_payload(result),
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
                "last_response_preview": response_preview(result),
            },
            status="needs_review",
        )
        await write_audit(
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

    async def attach_hitl_cards(
        self,
        formatted: FormatterTaskResult,
        *,
        thread_id: str,
        task_id: str,
        selected_strategy: str | None = None,
        task_kind: str | None = None,
        requires_user_choice: bool = False,
        underspecification_kind: str = "none",
        user_text: str | None = None,
        prior_context: str | None = None,
        user_id: str | None = None,
        org_id: str | None = None,
    ) -> FormatterTaskResult:
        """Сервер создаёт HITL-карточки; LLM actions не являются источником истины."""
        from palatium_ai.application.services.interaction_assembler import (
            InteractionAssembler,
            interaction_plan_log_fields,
        )
        from palatium_ai.domain.content import parse_content_document
        from palatium_ai.domain.hitl.option_synthesis import DiscreteChoiceSynthesisPolicy

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

        if (
            DiscreteChoiceSynthesisPolicy.needs_synthesis(
                requires_user_choice=requires_user_choice,
                underspecification_kind=underspecification_kind,
                plan=assembled.plan,
            )
            and self._option_synthesizer is not None
            and user_text
        ):
            synthesis = await self._option_synthesizer.synthesize(
                user_text=user_text,
                prior_context=prior_context,
            )
            logger.info(
                "hitl.option_synthesis",
                thread_id=thread_id,
                task_id=task_id,
                options=len(synthesis.actions),
                underspecification_kind=underspecification_kind,
            )
            if synthesis.actions:
                document = DiscreteChoiceSynthesisPolicy.merge_actions_into_document(
                    document,
                    synthesis.actions,
                    framing_text=synthesis.framing,
                )
                formatted = formatted.model_copy(update={"output": document})
                assembled = InteractionAssembler.assemble(
                    document,
                    requires_review=formatted.requires_review,
                    selected_strategy=strategy if isinstance(strategy, str) else None,
                    task_kind=task_kind,
                    requires_user_choice=True,
                )

        logger.info(
            "hitl.interaction_plan",
            thread_id=thread_id,
            task_id=task_id,
            task_kind=task_kind,
            selected_strategy=strategy,
            requires_user_choice=requires_user_choice,
            underspecification_kind=underspecification_kind,
            **interaction_plan_log_fields(assembled),
        )
        if assembled.invalid:
            agent_metrics.record_hitl_deny("formatter_output_invalid")
            await write_audit(
                conversation_id=thread_id,
                event="hitl_formatter_output_invalid",
                metadata={
                    "task_id": task_id,
                    "task_kind": task_kind or "",
                    "selected_strategy": str(strategy or ""),
                    "menu_shaped": str(assembled.plan.menu_shaped),
                    "promoted_from": assembled.plan.promoted_from,
                    "force_structural": str(assembled.plan.force_structural),
                    "underspecification_kind": underspecification_kind,
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
