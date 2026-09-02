# src/palatium_ai/application/services/intent_graph_runner.py

"""LangGraph invoke + formatted-state finalization for IntentService."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from palatium_ai.application.orchestration.run_config import build_graph_run_config
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.intent_turn_helpers import (
    assistant_turn_content,
    assistant_turn_payload,
    response_preview,
    write_audit,
)
from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import turn_hop_timings
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.turn_tokens import turn_token_usage
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.agents.intent import IntentTaskResult
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.sessions.context_privacy import session_user_text_preview

if TYPE_CHECKING:
    from langgraph.graph.state import CompiledStateGraph

    from palatium_ai.application.services.cost_budget import CostBudgetService
    from palatium_ai.application.services.memory_consolidation import MemoryConsolidationService
    from palatium_ai.application.services.session_service import SessionService
    from palatium_ai.domain.memory.ports import DialogTurnStore, MemoryPort

logger = get_logger(__name__)

_DEFAULT_DIALOG_WINDOW = 12

AttachHitlCards = Callable[..., Awaitable[FormatterTaskResult]]


class IntentGraphRunner:
    """Runs the agent graph and finalizes successful formatted turns."""

    def __init__(
        self,
        graph: CompiledStateGraph[AgentGraphState],
        *,
        session_service: SessionService,
        cost_budget: CostBudgetService,
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
        self._cost_budget = cost_budget
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
        self._attach_hitl_cards: AttachHitlCards | None = None

    def bind_attach_hitl_cards(self, attach: AttachHitlCards) -> None:
        """Wire HITL card minting after IntentHitlFlow is constructed."""
        self._attach_hitl_cards = attach

    @property
    def graph(self) -> CompiledStateGraph[AgentGraphState]:
        """Возвращает скомпилированный граф."""
        return self._graph

    @property
    def turn_hop_budget_ms(self) -> int:
        """Возвращает бюджет времени для перехода между узлами графа."""
        return self._turn_hop_budget_ms

    async def run_graph(
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
        dialog_window = await self.load_dialog_window(thread_id=thread_id)
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

    async def load_dialog_window(self, *, thread_id: str) -> DialogTurnWindow:
        """Загружает окно диалога из хранилища."""
        if self._dialog_turn_store is None:
            return DialogTurnWindow(thread_id=thread_id, turns=(), limit=self._dialog_window_size)
        return await self._dialog_turn_store.list_recent_turns(
            thread_id=thread_id,
            limit=self._dialog_window_size,
        )

    async def resolve_revision_user_text(self, *, thread_id: str, context: dict[str, object]) -> str:
        """Authoritative user text for quality revise: dialog turns, then session preview fallback."""
        window = await self.load_dialog_window(thread_id=thread_id)
        from_dialog = window.latest_user_content()
        if from_dialog:
            return from_dialog
        return str(context.get("effective_user_text") or context.get("last_user_text") or "").strip()

    async def finalize_formatted_state(
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
        if self._attach_hitl_cards is None:
            msg = "IntentGraphRunner.bind_attach_hitl_cards must be called before finalize"
            raise RuntimeError(msg)

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
        resolved_requires_user_choice = (
            bool(getattr(routing_intent, "requires_user_choice", False)) if routing_intent is not None else False
        )
        resolved_underspec = (
            str(getattr(routing_intent, "underspecification_kind", "none") or "none")
            if routing_intent is not None
            else "none"
        )
        prior_context = getattr(routing_intent, "prior_context", None) if routing_intent is not None else None
        effective_user_text = str(final_state.get("effective_user_text") or text)

        if isinstance(formatted, FormatterTaskResult):
            formatted = await self._attach_hitl_cards(
                formatted,
                thread_id=thread_id,
                task_id=task_id,
                selected_strategy=selected_strategy,
                task_kind=resolved_task_kind,
                requires_user_choice=resolved_requires_user_choice,
                underspecification_kind=resolved_underspec,
                user_text=effective_user_text,
                prior_context=prior_context if isinstance(prior_context, str) else None,
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
                    "last_operation": operation,
                    "last_task_id": task_id,
                    "last_task_kind": resolved_task_kind,
                    "last_status": formatted.status,
                    "requires_review": formatted.requires_review,
                    "last_response_preview": response_preview(formatted),
                    "hitl_card_ids": ",".join(card.card_id for card in formatted.hitl_cards),
                    "effective_user_text": session_user_text_preview(
                        str(final_state.get("effective_user_text") or text)
                    ),
                    "last_critic_summary": critic_summary,
                },
                status="needs_review" if formatted.requires_review else "active",
            )
            await write_audit(
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
