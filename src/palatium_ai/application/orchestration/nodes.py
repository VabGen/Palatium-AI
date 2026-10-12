# src/palatium_ai/application/orchestration/nodes.py

"""LangGraph node bodies — delegate agent execution to Harness (065)."""

from __future__ import annotations

import asyncio

from typing import TYPE_CHECKING, Literal

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
from palatium_ai.application.services.intent_hitl_flow import max_quality_revisions
from palatium_ai.application.services.memory_recall import recall_for_thread
from palatium_ai.application.services.routing_intent_resolver import resolve_routing_intent
from palatium_ai.application.services.turn_attachment_context import get_turn_attachment_context
from palatium_ai.application.services.turn_recall_context import get_turn_recall_context
from palatium_ai.core.exceptions import ClarifyError
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.span_names import (
    NODE_ANALYST,
    NODE_CODER,
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
    NODE_CRITIC,
    NODE_FORMATTER,
    NODE_INTENT,
    NODE_PARALLEL_WORKERS,
    NODE_QUALITY_REVISION,
    NODE_RESEARCHER,
    NODE_SUPERVISOR,
)
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.types.graph_nodes import (
    NODE_ANALYST as GRAPH_NODE_ANALYST,
    NODE_CODER as GRAPH_NODE_CODER,
    NODE_CONTEXT_ENRICHER_CONTINUATION as GRAPH_NODE_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING as GRAPH_NODE_WEAVING,
    NODE_CRITIC as GRAPH_NODE_CRITIC,
    NODE_FORMATTER as GRAPH_NODE_FORMATTER,
    NODE_INTENT_CLASSIFIER as GRAPH_NODE_INTENT,
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
from palatium_ai.domain.agents.intent import IntentClassifierInput
from palatium_ai.domain.agents.researcher import ResearcherInput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.recall import MemoryRecallBundle
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies import ContinuityPolicy, MemoryRecallPolicy
from palatium_ai.domain.policies.attachment_stickiness import AttachmentStickinessPolicy
from palatium_ai.domain.policies.parallel_workers import ParallelWorkerPolicy

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
        intent_decision = MemoryRecallPolicy.decide(
            task_kind=intent_task_kind,
            requires_mcp=intent_requires_mcp,
        )
        recall = await _maybe_deferred_durable_recall(
            state,
            decision=intent_decision,
        )
        memory_hints = recall.hint_texts if recall is not None else ()
        budget = state.get("prompt_budget") or MemoryPromptBudget()
        task_input = ContextualizerInput(
            task_id=selectors.require_task_id(state),
            user_text=selectors.resolved_user_text(state),
            dialog_window=window,
            memory_hints=memory_hints,
            prompt_budget=budget,
            task_kind=intent_task_kind,
            requires_mcp=intent_requires_mcp,
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
        entry_has_attachments = bool((state.get("untrusted_context") or "").strip())
        raw_user = state.get("user_text")
        routing_intent = resolve_routing_intent(
            contextualizer=output,
            dialog=window,
            raw_intent=raw_intent,
            has_turn_attachments=entry_has_attachments,
            user_text=raw_user if isinstance(raw_user, str) else None,
        )
        # SB2: rehydrate dialog-bound attachments after Continuity (not sticky poison).
        # Prefer Continuity trust over raw Contextualizer refers_to_prior — recovery of
        # false new_topic sets trust without rewriting the frozen Contextualizer output.
        untrusted_context = state.get("untrusted_context") or ""
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
        )
        agent_metrics.record_attachment_sticky(action=rehydrate.reason)
        attach_ctx = get_turn_attachment_context()
        if rehydrate.clear_pending and attach_ctx is not None and attach_ctx.clear_pending is not None:
            await attach_ctx.clear_pending()
        if rehydrate.attachment_ids and attach_ctx is not None and attach_ctx.rehydrate is not None and not entry_has_attachments:
            fenced = await attach_ctx.rehydrate(rehydrate.attachment_ids)
            if fenced.strip():
                untrusted_context = fenced
                agent_metrics.record_attachment_sticky(action="rehydrate_applied")

        effective_user_text = ContinuityPolicy.resolve_effective_user_text(
            raw_user_text=raw_user if isinstance(raw_user, str) else "",
            rewritten_query=rewritten,
            has_turn_attachments=entry_has_attachments,
        )
        # SB3: if Intent skipped (or narrowed) durable recall but Continuity remapped kind, fill now.
        routed_decision = MemoryRecallPolicy.decide(
            task_kind=routing_intent.task_kind,
            requires_mcp=routing_intent.requires_mcp,
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
    if not allowed:
        logger.info("memory_recall.skipped", reason=reason)
        agent_metrics.record_memory_recall_source(source="skipped_policy")
        return existing

    ctx = get_turn_recall_context()
    if ctx is None or ctx.memory_port is None:
        return existing

    return await recall_for_thread(
        ctx.memory_port,
        thread_id=ctx.thread_id,
        query=(query or "").strip() or ctx.query,
        user_id=ctx.user_id,
        org_id=ctx.org_id,
        limit=ctx.limit,
        max_chars=ctx.max_chars,
        min_confidence=ctx.min_confidence,
        scratchpad=ctx.scratchpad,
        kinds=kinds,
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
        task_input = IntentClassifierInput(
            task_id=selectors.require_task_id(state),
            text=text,
            continuation_kind=None,
            has_prior_dialog=has_prior,
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
        return {"classification": result}, result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_INTENT, state=state, run=run)


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
        return {"routing": result}, result

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
            hop = get_hop_collector()
            if hop is not None:
                hop.apply_strategy_budget(strategy)
            return {"context_bundle": result}, result
        except ClarifyError as exc:
            logger.info("Context weaver requires clarification", question=str(exc))
            return {
                "requires_clarification": True,
                "clarification_question": str(exc),
            }, TaskResultStub()

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_WEAVING, state=state, run=run)


def _emit_worker_answer_deltas(result: object) -> None:
    """Stream worker prose early (before Critic) for user-visible SSE TTFT."""
    from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
    from palatium_ai.application.agents.researcher.parsing import FAILURE_PLACEHOLDER_SUMMARY
    from palatium_ai.domain.agents.researcher import ResearcherTaskResult

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
        return {"critic": result}, result

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
        _emit_worker_answer_deltas(result)
        return {"execution": result}, result

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
        _emit_worker_answer_deltas(result)
        return {"execution": result}, result

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
        _emit_worker_answer_deltas(result)
        return {"execution": result}, result

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
        _emit_worker_answer_deltas(merged)
        return {"execution": merged}, merged

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


@traceable(name=NODE_FORMATTER)
async def formatter_node(
    state: AgentGraphState,
    agent: FormatterAgent,
    harness: Harness,
) -> AgentGraphState:
    async def run() -> tuple[AgentGraphState, object]:
        if state.get("requires_clarification"):
            return _formatter_clarification_result(state)
        mcp_failure = _mcp_failure_formatter_result(state)
        if mcp_failure is not None:
            return mcp_failure
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_formatter_input(snapshot, state)
        from palatium_ai.application.agents.formatter.fast_path import try_formatter_fast_path
        from palatium_ai.application.services.turn_response_cache import try_cached_formatter_result

        cached = await try_cached_formatter_result(
            task_input=task_input,
            selected_strategy=snapshot.selected_strategy,
        )
        if cached is not None:
            from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas

            if cached.output is not None:
                emit_answer_deltas(cached.output.plain_text())
            return {"formatted": cached}, cached
        fast = try_formatter_fast_path(
            task_input=task_input,
            task_kind=snapshot.task_kind,
            selected_strategy=snapshot.selected_strategy,
            agent_role=agent.config.role,
            worker_confidence=selectors.resolved_worker_confidence(state),
        )
        if fast is not None:
            return {"formatted": fast}, fast
        # Early TTFT: stream worker prose while Formatter LLM compiles ContentDocument.
        from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas

        emit_answer_deltas(task_input.worker_summary or "")
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
        return {"formatted": result}, result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_FORMATTER, state=state, run=run)


def _mcp_failure_formatter_result(
    state: AgentGraphState,
) -> tuple[AgentGraphState, FormatterTaskResult] | None:
    """Presentation for MCP empty/error. The graph still reaches Formatter."""
    from palatium_ai.application.agents.formatter.answer_delta import emit_answer_deltas
    from palatium_ai.application.agents.formatter.deterministic import aligned_document_from_source
    from palatium_ai.application.agents.formatter.messages import localized_message
    from palatium_ai.domain.agents.researcher import MCP_EMPTY_RESULT, MCP_TOOL_ERROR

    execution = state.get("execution")
    reason = execution.error if execution is not None else None
    if not isinstance(reason, str) or reason not in {MCP_EMPTY_RESULT, MCP_TOOL_ERROR}:
        return None
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
    return {"formatted": result}, result


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
    return {"formatted": result}, result


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
    # Terminal MCP empty/error cannot improve by re-calling the same tool (RC-4).
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
    """True when Researcher already failed closed on empty/error MCP — no revise."""
    from palatium_ai.domain.agents.researcher import MCP_EMPTY_RESULT, MCP_TOOL_ERROR

    execution = state.get("execution")
    if execution is None or execution.status != "failure":
        return False
    reason = execution.error
    return isinstance(reason, str) and reason in {MCP_EMPTY_RESULT, MCP_TOOL_ERROR}


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
