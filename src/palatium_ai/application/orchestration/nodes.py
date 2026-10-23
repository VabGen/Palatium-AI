# src/palatium_ai/application/orchestration/nodes.py

"""LangGraph node bodies — delegate agent execution to Harness (065)."""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Literal, cast

from langgraph.graph import END

from palatium_ai.application.orchestration import node_inputs, selectors
from palatium_ai.application.orchestration.agent_bridge import (
    analyst_output_to_execution_result,
    analyst_to_agent_input,
    coder_output_to_execution_result,
    coder_to_agent_input,
    context_weaver_output_to_task_result,
    context_weaver_to_agent_input,
    contextualizer_output_to_task_result,
    contextualizer_to_agent_input,
    critic_output_to_task_result,
    critic_to_agent_input,
    formatter_output_to_task_result,
    formatter_to_agent_input,
    intent_output_to_task_result,
    intent_to_agent_input,
    merge_parallel_worker_results,
    researcher_output_to_task_result,
    researcher_to_agent_input,
    supervisor_output_to_task_result,
    supervisor_to_agent_input,
)
from palatium_ai.application.orchestration.node_runtime import run_logged_node
from palatium_ai.application.orchestration.snapshot import OrchestrationSnapshot
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.orchestration.writer import current_owner, decide_and_record
from palatium_ai.application.services.attachment_prepare import AttachmentPrepareOutcome
from palatium_ai.application.services.intent_hitl_flow import max_quality_revisions
from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.application.services.routing_intent_resolver import resolve_routing_intent
from palatium_ai.application.services.turn_attachment_context import get_turn_attachment_context
from palatium_ai.application.services.turn_recall_context import get_turn_recall_context
from palatium_ai.core.exceptions import ClarifyError
from palatium_ai.core.logging import get_logger
from palatium_ai.core.logging.context import user_id_var
from palatium_ai.core.observability.adaptive_grounding import is_adaptive_grounding_enabled
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.span_names import (
    NODE_ANALYST,
    NODE_ATTACHMENT_SELECTION,
    NODE_CODER,
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
    NODE_CRITIC,
    NODE_FORMATTER,
    NODE_INTENT,
    NODE_MEMORY_MUTATION,
    NODE_PARALLEL_WORKERS,
    NODE_QUALITY_REVISION,
    NODE_RESEARCHER,
    NODE_SUPERVISOR,
)
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.types.graph_nodes import (
    NODE_ANALYST as GRAPH_NODE_ANALYST,
    NODE_ATTACHMENT_SELECTION as GRAPH_NODE_ATTACHMENT_SELECTION,
    NODE_CODER as GRAPH_NODE_CODER,
    NODE_CONTEXT_ENRICHER_CONTINUATION as GRAPH_NODE_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING as GRAPH_NODE_WEAVING,
    NODE_CRITIC as GRAPH_NODE_CRITIC,
    NODE_FORMATTER as GRAPH_NODE_FORMATTER,
    NODE_INTENT_CLASSIFIER as GRAPH_NODE_INTENT,
    NODE_MEMORY_MUTATION as GRAPH_NODE_MEMORY_MUTATION,
    NODE_PARALLEL_WORKERS as GRAPH_NODE_PARALLEL_WORKERS,
    NODE_QUALITY_REVISION as GRAPH_NODE_QUALITY_REVISION,
    NODE_RESEARCHER as GRAPH_NODE_RESEARCHER,
    NODE_SUPERVISOR as GRAPH_NODE_SUPERVISOR,
)
from palatium_ai.domain.agents import FormatterTaskResult
from palatium_ai.domain.agents.analyst import AnalystInput
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.execution import (
    ANALYST_STRATEGIES,
    CODER_STRATEGIES,
    RESEARCHER_STRATEGIES,
    WORKER_STRATEGIES,
)
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.agents.intent import IntentClassifierInput
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.attachments.context import AttachmentTurnContext, mime_kind
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.recall import MemoryRecallBundle
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies import ContinuityPolicy, MemoryRecallPolicy
from palatium_ai.domain.policies.attachment_stickiness import AttachmentStickinessPolicy
from palatium_ai.domain.policies.hop_budget import HopBudgetPolicy
from palatium_ai.domain.policies.parallel_workers import ParallelWorkerPolicy
from palatium_ai.domain.policies.types import TRANSFORMATION_DEFAULT

if TYPE_CHECKING:
    from palatium_ai.application.agents.analyst import AnalystAgent
    from palatium_ai.application.agents.coder import CoderAgent
    from palatium_ai.application.agents.context_enricher import ContextualizerAgent, ContextWeaverAgent
    from palatium_ai.application.agents.critic import CriticAgent
    from palatium_ai.application.agents.formatter import FormatterAgent
    from palatium_ai.application.agents.harness import Harness
    from palatium_ai.application.agents.intent_classifier import IntentClassifierAgent
    from palatium_ai.application.agents.researcher import ResearcherAgent
    from palatium_ai.application.agents.supervisor import SupervisorAgent
    from palatium_ai.application.services.attachment_prepare import AttachmentPrepareService
    from palatium_ai.application.services.memory_mutation import MemoryMutationGate

logger = get_logger(__name__)


def _thread_context(state: AgentGraphState) -> AgentContext:
    return AgentContext(
        thread_id=selectors.resolved_thread_id(state),
        user_id=(state.get("user_id") or "").strip() or None,
        org_id=(state.get("org_id") or "").strip() or None,
    )


def _trace_id(state: AgentGraphState) -> str:
    trace_id = state.get("trace_id")
    if isinstance(trace_id, str) and trace_id.strip():
        return trace_id
    return selectors.require_task_id(state)


@traceable(name=NODE_CONTEXT_ENRICHER_CONTINUATION)
async def continuation_node(
    state: AgentGraphState,
    agent: ContextualizerAgent,
    harness: Harness,
) -> AgentGraphState:
    """Rewrite follow-ups after Intent (task_kind known → ContextualizerPolicy can skip LLM)."""

    async def run() -> tuple[AgentGraphState, object]:
        window = state.get("dialog_window") or DialogTurnWindow(
            thread_id=selectors.resolved_thread_id(state),
            turns=(),
        )
        classification = state.get("classification")
        raw_intent = classification.output if classification is not None else None
        intent_task_kind = raw_intent.task_kind if raw_intent is not None else None
        intent_requires_mcp = bool(raw_intent.requires_mcp) if raw_intent is not None else False
        intent_transformation = raw_intent.transformation if raw_intent is not None else TRANSFORMATION_DEFAULT
        intent_decision = MemoryRecallPolicy.decide(
            task_kind=intent_task_kind,
            requires_mcp=intent_requires_mcp,
            transformation=intent_transformation,
        )
        recall = await _maybe_deferred_durable_recall(
            state,
            decision=intent_decision,
        )
        memory_hints = recall.hint_texts if recall is not None else ()
        budget = state.get("prompt_budget") or MemoryPromptBudget()
        intent_caps = tuple(raw_intent.candidate_capabilities) if raw_intent is not None else ()
        entry_untrusted_context = state.get("untrusted_context") or ""
        # Level 0: presence is decided by the typed attachment state, not by whether
        # a budgeted string happened to survive a trim (the old false-negative).
        entry_has_attachments = selectors.has_attachment_context(state)
        task_input = ContextualizerInput(
            task_id=selectors.require_task_id(state),
            user_text=selectors.resolved_user_text(state),
            dialog_window=window,
            memory_hints=memory_hints,
            prompt_budget=budget,
            task_kind=intent_task_kind,
            requires_mcp=intent_requires_mcp,
            candidate_capabilities=intent_caps,
            has_attachment_context=entry_has_attachments,
        )
        agent_input = contextualizer_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=selectors.resolved_thread_id(state),
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = contextualizer_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        output = getattr(result, "output", None)
        rewritten = output.rewritten_query if output is not None else selectors.resolved_user_text(state)
        raw_user = state.get("user_text")
        routing_intent = resolve_routing_intent(
            contextualizer=output,
            dialog=window,
            raw_intent=raw_intent,
            has_turn_attachments=entry_has_attachments,
            user_text=raw_user if isinstance(raw_user, str) else None,
            thread_file_named=bool(state.get("thread_file_named")),
        )
        # SB2: rehydrate dialog-bound attachments after Continuity (not sticky poison).
        # Prefer Continuity trust over raw Contextualizer refers_to_prior — recovery of
        # false new_topic sets trust without rewriting the frozen Contextualizer output.
        untrusted_context = entry_untrusted_context
        rehydrate_refers = (
            routing_intent.trust_prior_for_workers
            if routing_intent.continuation_kind in {"answer", "format"}
            else bool(output.refers_to_prior if output is not None else False)
        )
        rehydrate = AttachmentStickinessPolicy.decide_rehydrate(
            continuation_kind=routing_intent.continuation_kind,
            refers_to_prior=rehydrate_refers,
            has_turn_attachments=entry_has_attachments,
            dialog=window,
            prior_context=routing_intent.prior_context,
            trust_prior_for_workers=routing_intent.trust_prior_for_workers,
            grounding=routing_intent.grounding,
            adaptive_grounding_enabled=is_adaptive_grounding_enabled(user_id_var.get()),
            transformation=routing_intent.transformation,
        )
        agent_metrics.record_attachment_sticky(action=rehydrate.reason)
        logger.info(
            "attachment.build_turn_context",
            rehydrate_source=rehydrate.rehydrate_source,
            rehydrate_reason=rehydrate.reason,
            attachment_count=len(rehydrate.attachment_ids),
        )
        attach_ctx = get_turn_attachment_context()
        if rehydrate.clear_pending and attach_ctx is not None and attach_ctx.clear_pending is not None:
            await attach_ctx.clear_pending()
        if rehydrate.attachment_ids and attach_ctx is not None and attach_ctx.rehydrate is not None and not entry_has_attachments:
            fenced = await attach_ctx.rehydrate(rehydrate.attachment_ids)
            if fenced.strip():
                untrusted_context = fenced
                agent_metrics.record_attachment_sticky(action="rehydrate_applied")

        raw_ask = (raw_user if isinstance(raw_user, str) else "").strip()
        effective_user_text = ContinuityPolicy.resolve_effective_user_text(
            raw_user_text=raw_ask,
            rewritten_query=rewritten,
            has_turn_attachments=entry_has_attachments,
        )
        if not entry_has_attachments and rewritten.strip() and raw_ask and effective_user_text == raw_ask != rewritten.strip():
            # The rewrite dropped part of the user's own ask (it would answer an earlier
            # question); the raw ask wins. Visible in traces as a Contextualizer defect.
            logger.warning(
                "contextualizer.rewrite_dropped_user_ask",
                task_id=state.get("task_id"),
                rewritten_chars=len(rewritten),
                raw_chars=len(raw_ask),
            )
            agent_metrics.record_error("context_enricher", "continuation_rewrite_dropped_ask")
        # SB3: if Intent skipped (or narrowed) durable recall but Continuity remapped kind, fill now.
        routed_decision = MemoryRecallPolicy.decide(
            task_kind=routing_intent.task_kind,
            requires_mcp=routing_intent.requires_mcp,
            transformation=routing_intent.transformation,
        )
        recall_after = recall
        widened = routed_decision.kinds is None and intent_decision.kinds is not None
        if routed_decision.allowed and (not intent_decision.allowed or widened):
            recall_after = await _maybe_deferred_durable_recall(
                state,
                decision=routed_decision,
                existing_override=recall,
                query=effective_user_text,
            )
        elif recall_after is not None and routed_decision.pin_kinds is not None:
            # Continuity/Intent disagree on the transform axis: the earlier recall may
            # carry task facts and pinned intents. A content transform reads prior text,
            # so narrow the bundle instead of spending a second durable query (060/055).
            recall_after = recall_after.restrict_kinds(
                kinds=routed_decision.kinds,
                pin_kinds=routed_decision.pin_kinds,
            )
        update: AgentGraphState = {
            "contextualization": result,
            "effective_user_text": effective_user_text,
            "routing_intent": routing_intent,
            "untrusted_context": untrusted_context,
        }
        if recall_after is not None:
            update["memory_recall"] = recall_after
        return update, result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_CONTINUATION, state=state, run=run)


async def _maybe_deferred_durable_recall(
    state: AgentGraphState,
    *,
    decision: object,
    existing_override: MemoryRecallBundle | None = None,
    query: str | None = None,
) -> MemoryRecallBundle | None:
    """P1.5 + SB3: durable recall when MemoryRecallPolicy allows (Intent or Continuity).

    ``query`` overrides the raw ask with the Contextualizer's standalone rewrite once
    it exists: an anaphoric follow-up has no retrievable terms of its own.
    """
    existing = existing_override if existing_override is not None else state.get("memory_recall")
    allowed = bool(getattr(decision, "allowed", False))
    reason = str(getattr(decision, "reason", "unknown"))
    kinds = getattr(decision, "kinds", None)
    pin_kinds = getattr(decision, "pin_kinds", None)
    if not allowed:
        logger.info("memory_recall.skipped", reason=reason)
        agent_metrics.record_memory_recall_source(source="skipped_policy")
        return existing

    ctx = get_turn_recall_context()
    if ctx is None or ctx.memory_port is None:
        return existing

    recall_query: str = (query or "").strip() or ctx.query
    return await recall_for_thread(
        ctx.memory_port,
        thread_id=ctx.thread_id,
        query=recall_query,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        limit=ctx.limit,
        max_chars=ctx.max_chars,
        min_confidence=ctx.min_confidence,
        scratchpad=ctx.scratchpad,
        kinds=kinds,
        pin_kinds=pin_kinds,
        graph_write=ctx.graph_write,
        as_of=ctx.as_of,
    )


@traceable(name=NODE_INTENT)
async def intent_classifier_node(
    state: AgentGraphState,
    agent: IntentClassifierAgent,
    harness: Harness,
) -> AgentGraphState:
    """Classify raw user text first; Continuity runs in continuation after rewrite."""

    async def run() -> tuple[AgentGraphState, object]:
        dialog = state.get("dialog_window")
        text = state.get("effective_user_text") or selectors.resolved_user_text(state)
        has_prior = ContinuityPolicy.prior_assistant_content(None, dialog) is not None
        blocks = selectors.attachment_blocks(state)
        task_input = IntentClassifierInput(
            task_id=selectors.require_task_id(state),
            text=text,
            continuation_kind=None,
            has_prior_dialog=has_prior,
            has_thread_files=AttachmentStickinessPolicy.thread_has_files(dialog),
            attachment_count=len(blocks),
            attachment_kinds=_attachment_kinds(blocks),
        )
        agent_input = intent_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=selectors.resolved_thread_id(state),
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = intent_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        return cast("AgentGraphState", {"classification": result}), result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_INTENT, state=state, run=run)


@traceable(name=NODE_MEMORY_MUTATION)
async def memory_mutation_node(
    state: AgentGraphState,
    gate: MemoryMutationGate,
) -> AgentGraphState:
    """Explicit memory mutation: resolve the target, stage a HITL card, end the turn.

    Agentless by design (060/070): the write is an MCP call that only runs after the
    human approves the card, so no worker or formatter may phrase this turn as done.
    """
    classification = state.get("classification")
    output = classification.output if classification is not None else None
    kind = output.memory_mutation if output is not None else "none"
    result = await gate.handle(
        task_id=selectors.require_task_id(state),
        thread_id=selectors.resolved_thread_id(state),
        user_id=(state.get("user_id") or "").strip(),
        org_id=(state.get("org_id") or "").strip() or None,
        kind=kind,
        text=output.memory_text if output is not None else "",
        key=output.memory_key if output is not None else "",
        locale=str(state.get("response_locale") or ""),
    )
    return cast("AgentGraphState", {"formatted": result})


@traceable(name=NODE_ATTACHMENT_SELECTION)
async def attachment_selection_node(
    state: AgentGraphState,
    service: AttachmentPrepareService,
) -> AgentGraphState:
    """Select the ask's files and Map-Reduce their fences before any worker runs.

    Agentless by design: identity and modality are policy decisions, not LLM output.
    On ambiguity the turn ends with a file-choice card, so no worker gets to guess
    which document the user meant (020, 055). A one-file turn is already unambiguous
    and keeps its full fence.
    """
    classification = state.get("classification")
    output = classification.output if classification is not None else None
    blocks = selectors.attachment_blocks(state)
    # A file-choice card is only meaningful when the ask targets the uploads: with the
    # files set aside, three attachments are three irrelevant files, not an ambiguity.
    if output is None or len(blocks) <= 1 or not selectors.uploads_in_scope(state):
        return cast("AgentGraphState", {})
    outcome: AttachmentPrepareOutcome = await service.prepare(
        blocks=blocks,
        task_id=selectors.require_task_id(state),
        thread_id=selectors.resolved_thread_id(state),
        user_id=(state.get("user_id") or "").strip() or None,
        org_id=(state.get("org_id") or "").strip() or None,
        locale=selectors.resolved_response_locale(state),
        ask=selectors.resolved_user_text(state),
        scope=output.attachment_scope,
        kind=output.attachment_kind,
    )
    if outcome.status == "needs_choice" and outcome.result is not None:
        return cast("AgentGraphState", {"formatted": outcome.result})
    if outcome.status != "prepared":
        return cast("AgentGraphState", {})
    return cast(
        "AgentGraphState",
        {
            "attachment_context": AttachmentTurnContext(blocks=outcome.blocks),
            "untrusted_context": outcome.fenced_text,
        },
    )


def route_after_intent(
    state: AgentGraphState,
) -> Literal["memory_mutation", "attachment_selection", "context_enricher_continuation"]:
    """Mutation turns leave first; multi-file turns pass the attachment stage (065)."""
    classification = state.get("classification")
    output = classification.output if classification is not None else None
    if output is not None and output.memory_mutation != "none":
        return GRAPH_NODE_MEMORY_MUTATION
    if len(selectors.attachment_blocks(state)) > 1 and selectors.uploads_in_scope(state):
        return GRAPH_NODE_ATTACHMENT_SELECTION
    return GRAPH_NODE_CONTINUATION


def route_after_attachment_selection(state: AgentGraphState) -> str:
    """A pending file choice ends the turn; otherwise continue the normal pipeline."""
    if state.get("formatted") is not None:
        return END
    return GRAPH_NODE_CONTINUATION


def _attachment_kinds(blocks: tuple[object, ...]) -> tuple[Literal["image", "document"], ...]:
    """Distinct modalities present in the turn (closed Literal, stable order)."""
    seen: list[Literal["image", "document"]] = []
    for block in blocks:
        mime = getattr(block, "mime_type", "")
        kind = mime_kind(str(mime))
        if kind not in seen:
            seen.append(kind)
    return tuple(seen)


@traceable(name=NODE_SUPERVISOR)
async def supervisor_node(
    state: AgentGraphState,
    agent: SupervisorAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_supervisor_input(snapshot)
        agent_input = supervisor_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=snapshot.thread_id,
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = supervisor_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        return cast("AgentGraphState", {"routing": result}), result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_SUPERVISOR, state=state, run=run)


@traceable(name=NODE_CONTEXT_ENRICHER_WEAVING)
async def weaving_node(
    state: AgentGraphState,
    agent: ContextWeaverAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_context_weaver_input(snapshot, state)
        try:
            agent_input = context_weaver_to_agent_input(
                task_input,
                trace_id=_trace_id(state),
                thread_id=snapshot.thread_id,
            )
            agent_output = await harness.execute_with_guardrails(agent, agent_input)
            result = context_weaver_output_to_task_result(
                agent_output,
                task_id=task_input.task_id,
                agent_role=agent.config.role,
            )
            strategy = None
            if result.output is not None:
                strategy = str(result.output.execution_bundle.selected_strategy)
            from palatium_ai.core.observability.adaptive_grounding import is_adaptive_grounding_enabled

            # Sticky rollout decision recorded once per turn (not per planner/researcher check).
            is_adaptive_grounding_enabled(
                (state.get("user_id") or "").strip() or None,
                record=True,
            )
            agent_metrics.record_grounding_mode(str(task_input.grounding))
            agent_metrics.record_transform(kind=selectors.resolved_transformation(state))
            response_shape = str(selectors.resolved_response_shape(state))
            if response_shape != "auto":
                # Only explicit requests are interesting here; auto is the every-turn default.
                agent_metrics.record_response_shape(shape=response_shape, outcome="requested")
            logger.info(
                "agent.turn.grounding",
                grounding=task_input.grounding,
                grounding_reason=task_input.grounding_reason or "",
                response_shape=response_shape,
                strategy=strategy,
            )
            hop = get_hop_collector()
            if hop is not None:
                # HopBudgetPolicy is a domain policy; core cannot import domain (000),
                # so the collector takes it as an injected scaler port.
                hop.apply_strategy_budget(strategy, scaler=HopBudgetPolicy.effective_budget_ms)
            # One decision per turn, before any worker runs: the researcher must not
            # paint a draft the Formatter will own, and the Formatter must know
            # whether it may render deterministically (P1a/P1b).
            owner = decide_and_record(state)
            return cast(
                "AgentGraphState",
                {
                    "context_bundle": result,
                    "presentation_owner": owner.owner,
                    "presentation_owner_reason": owner.reason,
                },
            ), result
        except ClarifyError as exc:
            logger.info("Context weaver requires clarification", question=str(exc))
            return cast(
                "AgentGraphState",
                {
                    "requires_clarification": True,
                    "clarification_question": str(exc),
                },
            ), TaskResultStub()

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_WEAVING, state=state, run=run)


def _structured_preview_active() -> bool:
    """True when the terminal Formatter paints the document itself (no draft)."""
    from palatium_ai.application.services.turn_sse_bridge import get_turn_sse_bridge

    bridge = get_turn_sse_bridge()
    return bridge is not None and bridge.structured_preview_active()


def _emit_worker_answer_deltas(state: AgentGraphState, result: object) -> None:
    """Stream worker prose early (before Critic) for user-visible SSE TTFT.

    Only on worker-owned turns: there the final document is rendered from exactly
    this prose, so the draft is not replaced. On formatter-owned turns the draft
    would be overwritten by the Formatter's own composition — the layout shift the
    single-writer contract removes (055). Under ``structured_incremental`` the
    terminal document paints itself block by block, so nothing is painted here.
    """
    from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
    from palatium_ai.application.agents.researcher.parsing import FAILURE_PLACEHOLDER_SUMMARY
    from palatium_ai.domain.agents.researcher import ResearcherTaskResult

    if current_owner(state) != "worker":
        return
    if _structured_preview_active():
        return
    if not isinstance(result, ResearcherTaskResult):
        return
    if result.status == "failure" or result.output is None:
        return
    summary = result.output.summary.strip()
    if not summary or summary == FAILURE_PLACEHOLDER_SUMMARY:
        return
    emit_answer_deltas(summary)


@traceable(name=NODE_CRITIC)
async def critic_node(
    state: AgentGraphState,
    agent: CriticAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_critic_input(snapshot, state)
        agent_input = critic_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=snapshot.thread_id,
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = critic_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        return cast("AgentGraphState", {"critic": result}), result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_CRITIC, state=state, run=run)


@traceable(name=NODE_RESEARCHER)
async def researcher_node(
    state: AgentGraphState,
    agent: ResearcherAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_researcher_input(snapshot, state)
        agent_input = researcher_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=snapshot.thread_id,
            user_id=(state.get("user_id") or "").strip(),
            org_id=(state.get("org_id") or "").strip(),
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = researcher_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        _emit_worker_answer_deltas(state, result)
        update: dict[str, object] = {"execution": result}
        if result.cannot_answer_without_source:
            question = (
                result.output.summary
                if result.output is not None and result.output.summary.strip()
                else "Уточните источник данных или приложите файл."
            )
            update["requires_clarification"] = True
            update["clarification_question"] = question
        return cast("AgentGraphState", update), result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_RESEARCHER, state=state, run=run)


@traceable(name=NODE_CODER)
async def coder_node(
    state: AgentGraphState,
    agent: CoderAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_coder_input(snapshot, state)
        agent_input = coder_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=snapshot.thread_id,
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = coder_output_to_execution_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        _emit_worker_answer_deltas(state, result)
        return cast("AgentGraphState", {"execution": result}), result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_CODER, state=state, run=run)


@traceable(name=NODE_ANALYST)
async def analyst_node(
    state: AgentGraphState,
    agent: AnalystAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_analyst_input(snapshot, state)
        agent_input = analyst_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=snapshot.thread_id,
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = analyst_output_to_execution_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        _emit_worker_answer_deltas(state, result)
        return cast("AgentGraphState", {"execution": result}), result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_ANALYST, state=state, run=run)


def _step_for_strategies(
    steps: tuple[ToolExecutionPlan, ...],
    strategies: frozenset[str],
) -> ToolExecutionPlan | None:
    for step in steps:
        if step.strategy in strategies:
            return step
    return None


@traceable(name=NODE_PARALLEL_WORKERS)
async def parallel_workers_node(
    state: AgentGraphState,
    researcher: ResearcherAgent,
    analyst: AnalystAgent,
    harness: Harness,
) -> AgentGraphState:
    """Fan-out Researcher∥Analyst for multi-capability plans (P2.15)."""

    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        steps = selectors.execution_plan_steps(state)
        research_plan = _step_for_strategies(steps, RESEARCHER_STRATEGIES)
        analyst_plan = _step_for_strategies(steps, ANALYST_STRATEGIES)
        if research_plan is None or analyst_plan is None:
            raise ValueError("parallel_workers requires research and analyst steps in execution_bundle")

        base_packet = snapshot.context_packet(
            state,
            fallback_strategy=research_plan.strategy,
            fallback_rationale="Parallel workers require a context packet before execution.",
        )
        research_input = ResearcherInput(
            task_id=snapshot.task_id,
            context_packet=base_packet.model_copy(update={"execution_plan": research_plan}),
            prior_context=selectors.resolved_prior_assistant_content(state),
            mcp_tool_output_max_chars=selectors.prompt_budget(state).mcp_tool_output_max_chars,
            revision_feedback=selectors.resolved_revision_feedback(state),
        )
        analyst_input = AnalystInput(
            task_id=snapshot.task_id,
            context_packet=base_packet.model_copy(update={"execution_plan": analyst_plan}),
            revision_feedback=selectors.resolved_revision_feedback(state),
        )

        async def _run_researcher() -> object:
            agent_input = researcher_to_agent_input(
                research_input,
                trace_id=_trace_id(state),
                thread_id=snapshot.thread_id,
                user_id=(state.get("user_id") or "").strip(),
                org_id=(state.get("org_id") or "").strip(),
            )
            agent_output = await harness.execute_with_guardrails(researcher, agent_input)
            return researcher_output_to_task_result(
                agent_output,
                task_id=research_input.task_id,
                agent_role=researcher.config.role,
            )

        async def _run_analyst() -> object:
            agent_input = analyst_to_agent_input(
                analyst_input,
                trace_id=_trace_id(state),
                thread_id=snapshot.thread_id,
            )
            agent_output = await harness.execute_with_guardrails(analyst, agent_input)
            return analyst_output_to_execution_result(
                agent_output,
                task_id=analyst_input.task_id,
                agent_role=analyst.config.role,
            )

        research_result, analyst_result = await asyncio.gather(_run_researcher(), _run_analyst())
        merged = merge_parallel_worker_results(research_result, analyst_result)  # type: ignore[arg-type]
        _emit_worker_answer_deltas(state, merged)
        return cast("AgentGraphState", {"execution": merged}), merged

    return await run_logged_node(
        agent=researcher,
        node_name=GRAPH_NODE_PARALLEL_WORKERS,
        state=state,
        run=run,
    )


@traceable(name=NODE_QUALITY_REVISION)
async def quality_revision_node(state: AgentGraphState) -> AgentGraphState:
    """Bump revisions_count and seed revision_feedback from Critic before re-running worker."""
    critic = state.get("critic")
    summary = "Improve the previous draft using critic feedback."
    if critic is not None and critic.output is not None and critic.output.summary.strip():
        summary = critic.output.summary.strip()[:4_000]
    return {
        "revision_feedback": summary,
        "revisions_count": int(state.get("revisions_count") or 0) + 1,
    }


def _try_worker_owned_document(
    agent: FormatterAgent,
    state: AgentGraphState,
    task_input: FormatterInput,
) -> FormatterTaskResult | None:
    """Render the worker draft without an LLM, or hand the turn to the Formatter.

    The fallback also restores early TTFT: a draft is painted once before the LLM
    pass (legacy contract allows exactly one handover; structured preview paints
    its own blocks and is left silent).
    """
    from palatium_ai.application.agents.formatter.answer_delta import (
        emit_answer_deltas,
        emit_document_block,
        emit_document_title,
    )
    from palatium_ai.application.agents.formatter.worker_writer import render_worker_document

    decision = render_worker_document(
        task_input,
        worker_confidence=selectors.resolved_worker_confidence(state),
    )
    if not decision.rendered or decision.document is None:
        agent_metrics.record_node_execution(agent.config.role, f"worker_writer:fallback:{decision.reason}")
        logger.info(
            "formatter.worker_writer.fallback",
            task_id=str(task_input.task_id),
            reason=decision.reason,
        )
        if not _structured_preview_active():
            emit_answer_deltas(task_input.worker_summary or "")
        return None

    document = decision.document
    if _structured_preview_active():
        # The deterministic document already exists: paint it additively, so a
        # worker-owned turn keeps early TTFT instead of waiting for the final result.
        if document.title:
            emit_document_title(document.title)
        for index, block in enumerate(document.blocks):
            emit_document_block(index=index, block=block)
    agent_metrics.record_node_execution(agent.config.role, "emit:deterministic_gfm")
    logger.info(
        "formatter.worker_writer",
        task_id=str(task_input.task_id),
        reason=decision.reason,
        blocks=len(document.blocks),
        locale=document.locale,
    )
    status: Literal["success", "partial"] = "partial" if task_input.requires_review else "success"
    return FormatterTaskResult(
        task_id=task_input.task_id,
        agent_role=agent.config.role,
        status=status,
        confidence=document.meta.confidence,
        requires_review=task_input.requires_review,
        output=document,
    )


@traceable(name=NODE_FORMATTER)
async def formatter_node(
    state: AgentGraphState,
    agent: FormatterAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        # Attached-but-unreadable is a deterministic answer, not a prompt hint: the
        # LLM used to greet the user when the fence held only the no-text notice
        # (Level 3 anti-hallucination, 020/055).
        attachment_failure = _attachment_failure_formatter_result(state)
        if attachment_failure is not None:
            return attachment_failure
        if state.get("requires_clarification"):
            return _formatter_clarification_result(state)
        mcp_failure = _mcp_failure_formatter_result(state)
        if mcp_failure is not None:
            return mcp_failure
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_formatter_input(snapshot, state)
        from palatium_ai.application.agents.formatter.fast_path import try_formatter_fast_path
        from palatium_ai.application.services.turn_response_cache import try_cached_formatter_result

        routing_intent = state.get("routing_intent")
        cached = await try_cached_formatter_result(
            task_input=task_input,
            selected_strategy=snapshot.selected_strategy,
            dialog_window=state.get("dialog_window"),
            continuation_kind=selectors.resolved_continuation_kind(state),
            trust_prior_for_workers=bool(routing_intent is not None and routing_intent.trust_prior_for_workers),
            has_turn_attachments=bool((state.get("untrusted_context") or "").strip()),
        )
        if cached is not None:
            from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas

            if cached.output is not None:
                emit_answer_deltas(cached.output.plain_text())
            return cast("AgentGraphState", {"formatted": cached}), cached
        if current_owner(state) == "worker":
            worker_result = _try_worker_owned_document(agent, state, task_input)
            if worker_result is not None:
                return cast("AgentGraphState", {"formatted": worker_result}), worker_result
        fast = try_formatter_fast_path(
            task_input=task_input,
            task_kind=snapshot.task_kind,
            selected_strategy=snapshot.selected_strategy,
            agent_role=agent.config.role,
            worker_confidence=selectors.resolved_worker_confidence(state),
        )
        if fast is not None:
            return cast("AgentGraphState", {"formatted": fast}), fast
        agent_input = formatter_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=snapshot.thread_id,
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = formatter_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        return cast("AgentGraphState", {"formatted": result}), result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_FORMATTER, state=state, run=run)


def _attachment_failure_formatter_result(
    state: AgentGraphState,
) -> tuple[AgentGraphState, FormatterTaskResult] | None:
    """Honest answer when every attached file is attached-but-unreadable.

    Trigger is typed state (``AttachmentContextBlock.text_state``), not a text
    heuristic; a worker that successfully read the file via ``read_attachment``
    already has a non-empty draft and keeps it (no false override).
    """
    from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
    from palatium_ai.application.agents.formatter.deterministic import aligned_document_from_source
    from palatium_ai.application.agents.formatter.messages import localized_message

    ctx = selectors.attachment_context(state)
    if ctx is None or not ctx.all_text_missing:
        return None
    if not selectors.uploads_in_scope(state):
        # The user set the files aside («вопрос не про файлы»): the honest-failure
        # line would answer a question they did not ask (055, Level 3 gate).
        return None
    execution = state.get("execution")
    if execution is not None and execution.status == "success":
        summary = execution.output.summary if execution.output is not None else ""
        if summary.strip():
            return None
    snapshot = OrchestrationSnapshot.from_state(state)
    task_input = node_inputs.build_formatter_input(snapshot, state)
    text = localized_message(
        task_input.response_locale,
        "attachment_text_unavailable",
        user_text=selectors.resolved_user_text(state),
    )
    if not text:
        return None
    document, _mode = aligned_document_from_source(text, task_input=task_input, confidence=0.0)
    emit_answer_deltas(text)
    result = FormatterTaskResult(
        task_id=task_input.task_id,
        agent_role="formatter",
        status="success",
        confidence=document.meta.confidence,
        requires_review=False,
        output=document,
        error="attachment_text_unavailable",
    )
    return cast("AgentGraphState", {"formatted": result}), result


def _mcp_failure_formatter_result(
    state: AgentGraphState,
) -> tuple[AgentGraphState, FormatterTaskResult] | None:
    """Presentation for MCP empty/error. The graph still reaches Formatter.

    Adaptive Grounding ON: ``mcp_empty_result`` is not stubbed here (optional→LLM
    already answered; required→clarification). Tool errors still use localized copy.
    """
    from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
    from palatium_ai.application.agents.formatter.deterministic import aligned_document_from_source
    from palatium_ai.application.agents.formatter.messages import localized_message
    from palatium_ai.core.observability.adaptive_grounding import is_adaptive_grounding_enabled
    from palatium_ai.domain.agents.researcher import MCP_EMPTY_RESULT, MCP_SERVER_UNAVAILABLE, MCP_TOOL_ERROR

    execution = state.get("execution")
    reason = execution.error if execution is not None else None
    if not isinstance(reason, str):
        return None
    if reason == MCP_SERVER_UNAVAILABLE:
        # Degradation is a capability statement, not an error plaque: name the module
        # and what still works (local uploads) — Level 5, 035.
        return _mcp_degraded_formatter_result(state, reason=reason)
    adaptive = is_adaptive_grounding_enabled((state.get("user_id") or "").strip() or None)
    if reason == MCP_EMPTY_RESULT and adaptive:
        return None
    if reason not in {MCP_EMPTY_RESULT, MCP_TOOL_ERROR}:
        return None
    if reason == MCP_EMPTY_RESULT and not adaptive:
        from palatium_ai.core.logging import get_logger

        get_logger(__name__).warning(
            "formatter.mcp_empty_stub",
            fallback_disabled=True,
            adaptive_grounding_enabled=False,
            reason=reason,
        )
    snapshot = OrchestrationSnapshot.from_state(state)
    task_input = node_inputs.build_formatter_input(snapshot, state)
    text = localized_message(
        task_input.response_locale,
        reason,
        user_text=selectors.resolved_user_text(state),
    )
    if not text:
        return None
    document, _mode = aligned_document_from_source(text, task_input=task_input, confidence=0.0)
    emit_answer_deltas(text)
    result = FormatterTaskResult(
        task_id=task_input.task_id,
        agent_role="formatter",
        status="success",
        confidence=document.meta.confidence,
        requires_review=False,
        output=document,
    )
    return cast("AgentGraphState", {"formatted": result}), result


def _mcp_degraded_formatter_result(
    state: AgentGraphState,
    *,
    reason: str,
) -> tuple[AgentGraphState, FormatterTaskResult] | None:
    """Degradation copy: name the missing module, offer what still works (Level 5).

    The message variant follows the turn: with local uploads the answer states that
    they can still be analysed; without them it points at the unavailable capability
    instead of pretending the request ran (035).
    """
    from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
    from palatium_ai.application.agents.formatter.deterministic import aligned_document_from_source
    from palatium_ai.application.agents.formatter.messages import localized_message

    snapshot = OrchestrationSnapshot.from_state(state)
    task_input = node_inputs.build_formatter_input(snapshot, state)
    has_local_files = selectors.uploads_in_scope(state) and bool(selectors.attachment_blocks(state))
    key = f"{reason}_with_files" if has_local_files else reason
    text = localized_message(task_input.response_locale, key, user_text=selectors.resolved_user_text(state))
    if not text:
        return None
    document, _mode = aligned_document_from_source(text, task_input=task_input, confidence=0.0)
    emit_answer_deltas(text)
    result = FormatterTaskResult(
        task_id=task_input.task_id,
        agent_role="formatter",
        status="success",
        confidence=document.meta.confidence,
        requires_review=False,
        output=document,
        error=reason,
    )
    return cast("AgentGraphState", {"formatted": result}), result


def _formatter_clarification_result(
    state: AgentGraphState,
) -> tuple[AgentGraphState, FormatterTaskResult]:
    from palatium_ai.domain.content import ContentDocument
    from palatium_ai.domain.content.content_document import DocumentMeta, ParagraphBlock

    question = state.get("clarification_question") or "?"
    locale = selectors.resolved_response_locale(state)
    doc = ContentDocument(
        schema_version=1,
        locale=locale,
        title=None,
        blocks=(ParagraphBlock(type="paragraph", text=str(question)[:8000]),),
        actions=(),
        meta=DocumentMeta(
            confidence=1.0,
            requires_review=False,
            source_refs=(),
            interaction="none",
        ),
    )
    result = FormatterTaskResult(
        task_id=selectors.require_task_id(state),
        agent_role="formatter",
        status="success",
        confidence=1.0,
        requires_review=False,
        output=doc,
    )
    return cast("AgentGraphState", {"formatted": result}), result


def route_after_context(
    state: AgentGraphState,
) -> Literal["researcher", "coder", "analyst", "parallel_workers", "critic", "formatter"]:
    if state.get("requires_clarification"):
        return GRAPH_NODE_FORMATTER
    snapshot = OrchestrationSnapshot.from_state(state)
    strategy = snapshot.selected_strategy
    # Clarify and true response_formatting skip Critic at the edge (CriticPolicy would
    # passthrough). Social also uses format_only (2026) — must go through Critic.
    if strategy == "clarify":
        return GRAPH_NODE_FORMATTER
    if strategy == "format_only" and snapshot.task_kind == "response_formatting":
        return GRAPH_NODE_FORMATTER
    steps = selectors.execution_plan_steps(state)
    if ParallelWorkerPolicy.decide_from_steps(steps).parallel:
        return GRAPH_NODE_PARALLEL_WORKERS
    if strategy in CODER_STRATEGIES:
        return GRAPH_NODE_CODER
    if strategy in ANALYST_STRATEGIES:
        return GRAPH_NODE_ANALYST
    if strategy in RESEARCHER_STRATEGIES or strategy in WORKER_STRATEGIES:
        return GRAPH_NODE_RESEARCHER
    return GRAPH_NODE_CRITIC


def route_after_critic(state: AgentGraphState) -> Literal["quality_revision", "formatter"]:
    """Critic → worker revision loop (bounded) or Formatter (HITL/finalize)."""
    # Required-empty clarification and terminal MCP empty/error cannot improve via revision.
    if state.get("requires_clarification"):
        return GRAPH_NODE_FORMATTER
    if _terminal_mcp_worker_failure(state):
        return GRAPH_NODE_FORMATTER
    critic = state.get("critic")
    if critic is not None and critic.requires_review:
        count = int(state.get("revisions_count") or 0)
        if count < max_quality_revisions():
            snapshot = OrchestrationSnapshot.from_state(state)
            if snapshot.selected_strategy in WORKER_STRATEGIES:
                return GRAPH_NODE_QUALITY_REVISION
            if ParallelWorkerPolicy.decide_from_steps(selectors.execution_plan_steps(state)).parallel:
                return GRAPH_NODE_QUALITY_REVISION
    return GRAPH_NODE_FORMATTER


def _terminal_mcp_worker_failure(state: AgentGraphState) -> bool:
    """True when Researcher already closed on empty/error MCP — no revise."""
    from palatium_ai.domain.agents.researcher import (
        ATTACHMENT_REFERENCE_UNRESOLVED,
        GROUNDING_REQUIRED_EMPTY,
        MCP_EMPTY_RESULT,
        MCP_SERVER_UNAVAILABLE,
        MCP_TOOL_ERROR,
    )

    execution = state.get("execution")
    if execution is None or execution.status == "success":
        return False
    if getattr(execution, "cannot_answer_without_source", False):
        return True
    reason = execution.error
    return isinstance(reason, str) and reason in {
        MCP_EMPTY_RESULT,
        MCP_TOOL_ERROR,
        # A downed module will not come back within one revision: report degradation.
        MCP_SERVER_UNAVAILABLE,
        GROUNDING_REQUIRED_EMPTY,
        # The thread's file set cannot change on retry: revision is pure waste.
        ATTACHMENT_REFERENCE_UNRESOLVED,
    }


def route_after_quality_revision(
    state: AgentGraphState,
) -> Literal["researcher", "coder", "analyst", "parallel_workers"]:
    if ParallelWorkerPolicy.decide_from_steps(selectors.execution_plan_steps(state)).parallel:
        return GRAPH_NODE_PARALLEL_WORKERS
    snapshot = OrchestrationSnapshot.from_state(state)
    strategy = snapshot.selected_strategy
    if strategy in CODER_STRATEGIES:
        return GRAPH_NODE_CODER
    if strategy in ANALYST_STRATEGIES:
        return GRAPH_NODE_ANALYST
    return GRAPH_NODE_RESEARCHER


class TaskResultStub:
    """Placeholder when ClarifyError short-circuits context weaver."""

    status = "partial"
    confidence = 0.5
    requires_review = True
