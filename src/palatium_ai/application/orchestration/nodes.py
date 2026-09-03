# src/palatium_ai/application/orchestration/nodes.py

"""LangGraph node bodies — delegate agent execution to Harness (065)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from palatium_ai.application.orchestration import node_inputs
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
    researcher_output_to_task_result,
    researcher_to_agent_input,
    supervisor_output_to_task_result,
    supervisor_to_agent_input,
)
from palatium_ai.application.orchestration.node_runtime import run_logged_node
from palatium_ai.application.orchestration.snapshot import OrchestrationSnapshot
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.application.services.intent_hitl_flow import max_quality_revisions
from palatium_ai.application.services.routing_intent_resolver import resolve_routing_intent
from palatium_ai.core.exceptions import ClarifyError
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.span_names import (
    NODE_ANALYST,
    NODE_CODER,
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
    NODE_CRITIC,
    NODE_FORMATTER,
    NODE_INTENT,
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
    NODE_QUALITY_REVISION as GRAPH_NODE_QUALITY_REVISION,
    NODE_RESEARCHER as GRAPH_NODE_RESEARCHER,
    NODE_SUPERVISOR as GRAPH_NODE_SUPERVISOR,
)
from palatium_ai.domain.agents import FormatterTaskResult
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.execution import (
    ANALYST_STRATEGIES,
    CODER_STRATEGIES,
    RESEARCHER_STRATEGIES,
    WORKER_STRATEGIES,
)
from palatium_ai.domain.agents.intent import IntentClassifierInput
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies import ContinuityPolicy

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
        thread_id=state.get("thread_id", state["task_id"]),
        user_id=(state.get("user_id") or "").strip() or None,
        org_id=(state.get("org_id") or "").strip() or None,
    )


def _trace_id(state: AgentGraphState) -> str:
    return state.get("trace_id", state["task_id"])


@traceable(name=NODE_CONTEXT_ENRICHER_CONTINUATION)
async def continuation_node(
    state: AgentGraphState,
    agent: ContextualizerAgent,
    harness: Harness,
) -> AgentGraphState:
    """Rewrite follow-ups before Intent; Continuity runs after classification."""

    async def run() -> tuple[AgentGraphState, object]:
        window = state.get("dialog_window") or DialogTurnWindow(
            thread_id=state.get("thread_id", state["task_id"]),
            turns=(),
        )
        recall = state.get("memory_recall")
        memory_hints = recall.hint_texts if recall is not None else ()
        budget = state.get("prompt_budget") or MemoryPromptBudget()
        task_input = ContextualizerInput(
            task_id=state["task_id"],
            user_text=state["user_text"],
            dialog_window=window,
            memory_hints=memory_hints,
            prompt_budget=budget,
            task_kind=None,
            requires_mcp=False,
        )
        agent_input = contextualizer_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=state.get("thread_id", state["task_id"]),
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = contextualizer_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        output = getattr(result, "output", None)
        rewritten = output.rewritten_query if output is not None else state["user_text"]
        return {
            "contextualization": result,
            "effective_user_text": rewritten,
        }, result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_CONTINUATION, state=state, run=run)


@traceable(name=NODE_INTENT)
async def intent_classifier_node(
    state: AgentGraphState,
    agent: IntentClassifierAgent,
    harness: Harness,
) -> AgentGraphState:
    """Classify rewritten text + live continuation hints; then ContinuityPolicy."""

    async def run() -> tuple[AgentGraphState, object]:
        dialog = state.get("dialog_window")
        ctx_result = state.get("contextualization")
        ctx_out = ctx_result.output if ctx_result is not None else None
        text = state.get("effective_user_text") or state["user_text"]
        has_prior = (ctx_out is not None and ctx_out.refers_to_prior) or ContinuityPolicy.prior_assistant_content(
            ctx_out, dialog
        ) is not None
        task_input = IntentClassifierInput(
            task_id=state["task_id"],
            text=text,
            continuation_kind=ctx_out.continuation_kind if ctx_out is not None else None,
            has_prior_dialog=has_prior,
        )
        agent_input = intent_to_agent_input(
            task_input,
            trace_id=_trace_id(state),
            thread_id=state.get("thread_id", state["task_id"]),
        )
        agent_output = await harness.execute_with_guardrails(agent, agent_input)
        result = intent_output_to_task_result(
            agent_output,
            task_id=task_input.task_id,
            agent_role=agent.config.role,
        )
        routing_intent = resolve_routing_intent(
            contextualizer=ctx_out,
            dialog=dialog,
            raw_intent=getattr(result, "output", None),
        )
        return {
            "classification": result,
            "routing_intent": routing_intent,
        }, result

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
        task_input = node_inputs.build_context_weaver_input(snapshot)
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
            return {"context_bundle": result}, result
        except ClarifyError as exc:
            logger.info("Context weaver requires clarification", question=str(exc))
            return {
                "requires_clarification": True,
                "clarification_question": str(exc),
            }, TaskResultStub()

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_WEAVING, state=state, run=run)


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
        return {"execution": result}, result

    return await run_logged_node(agent=agent, node_name=GRAPH_NODE_ANALYST, state=state, run=run)


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
            question = state.get("clarification_question", "Уточните, пожалуйста.")
            from palatium_ai.domain.content import ContentDocument
            from palatium_ai.domain.content.content_document import DocumentMeta, ParagraphBlock

            doc = ContentDocument(
                schema_version=1,
                locale="ru-RU",
                title="Уточнение",
                blocks=(ParagraphBlock(type="paragraph", text=str(question)),),
                actions=(),
                meta=DocumentMeta(
                    confidence=1.0,
                    requires_review=False,
                    source_refs=(),
                    interaction="none",
                ),
            )
            result = FormatterTaskResult(
                task_id=state["task_id"],
                agent_role="formatter",
                status="success",
                confidence=1.0,
                requires_review=False,
                output=doc,
            )
            return {"formatted": result}, result
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_formatter_input(snapshot, state)
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


def route_after_context(
    state: AgentGraphState,
) -> Literal["researcher", "coder", "analyst", "critic", "formatter"]:
    if state.get("requires_clarification"):
        return GRAPH_NODE_FORMATTER
    snapshot = OrchestrationSnapshot.from_state(state)
    strategy = snapshot.selected_strategy
    if strategy in CODER_STRATEGIES:
        return GRAPH_NODE_CODER
    if strategy in ANALYST_STRATEGIES:
        return GRAPH_NODE_ANALYST
    if strategy in RESEARCHER_STRATEGIES or strategy in WORKER_STRATEGIES:
        return GRAPH_NODE_RESEARCHER
    return GRAPH_NODE_CRITIC


def route_after_critic(state: AgentGraphState) -> Literal["quality_revision", "formatter"]:
    """Critic → worker revision loop (bounded) or Formatter (HITL/finalize)."""
    critic = state.get("critic")
    if critic is not None and critic.requires_review:
        count = int(state.get("revisions_count") or 0)
        if count < max_quality_revisions():
            snapshot = OrchestrationSnapshot.from_state(state)
            if snapshot.selected_strategy in WORKER_STRATEGIES:
                return GRAPH_NODE_QUALITY_REVISION
    return GRAPH_NODE_FORMATTER


def route_after_quality_revision(
    state: AgentGraphState,
) -> Literal["researcher", "coder", "analyst"]:
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
