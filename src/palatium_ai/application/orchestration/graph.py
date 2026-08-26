# src/palatium_ai/application/orchestration/graph.py

"""LangGraph StateGraph — Contextualizer → Intent → Supervisor → Weaver → Worker → Critic → Formatter."""

from __future__ import annotations

from time import perf_counter, time
from typing import TYPE_CHECKING, Any, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from palatium_ai.application.orchestration import node_inputs
from palatium_ai.application.orchestration.snapshot import OrchestrationSnapshot
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.hop_timings import get_hop_collector
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.contracts import AgentContext
from palatium_ai.domain.agents.execution import WORKER_STRATEGIES
from palatium_ai.domain.agents.intent import IntentClassifierInput
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.contextualizer import ContextualizerInput
from palatium_ai.domain.memory.continuity import ContinuityPolicy
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.infrastructure.memory.checkpoint_serde import build_checkpoint_serde
from palatium_ai.infrastructure.resilience.circuit import (
    CircuitOpenError,
    ConsecutiveFailureCircuit,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

    from palatium_ai.application.agents.context_weaver_agent import ContextWeaverAgent
    from palatium_ai.application.agents.contextualizer_agent import ContextualizerAgent
    from palatium_ai.application.agents.critic_agent import CriticAgent
    from palatium_ai.application.agents.formatter_agent import FormatterAgent
    from palatium_ai.application.agents.intent_classifier_agent import IntentClassifierAgent
    from palatium_ai.application.agents.researcher_agent import ResearcherAgent
    from palatium_ai.application.agents.supervisor_agent import SupervisorAgent

logger = get_logger(__name__)

_NODE_CIRCUITS: dict[str, ConsecutiveFailureCircuit] = {}


def _node_circuit(node_name: str) -> ConsecutiveFailureCircuit:
    return _NODE_CIRCUITS.setdefault(node_name, ConsecutiveFailureCircuit())


def reset_node_circuits_for_tests() -> None:
    """Clear agent-node circuits (unit tests only)."""
    _NODE_CIRCUITS.clear()


def _agent_identity(agent: object, *, fallback: str) -> tuple[str, str]:
    config = getattr(agent, "config", None)
    name = getattr(config, "name", None)
    role = getattr(config, "role", None)
    return (
        name if isinstance(name, str) and name else fallback,
        role if isinstance(role, str) and role else fallback,
    )


def _result_fields(result: object) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    status = getattr(result, "status", None)
    if isinstance(status, str):
        fields["status"] = status
    confidence = getattr(result, "confidence", None)
    if isinstance(confidence, (int, float)):
        fields["confidence"] = round(float(confidence), 3)
    requires_review = getattr(result, "requires_review", None)
    if isinstance(requires_review, bool):
        fields["requires_review"] = requires_review
    error = getattr(result, "error", None)
    if isinstance(error, str) and error:
        fields["error"] = error
    return fields


async def _run_logged_node(
    *,
    agent: object,
    node_name: str,
    state: AgentGraphState,
    run: Callable[[], Awaitable[tuple[AgentGraphState, object]]],
) -> AgentGraphState:
    """Запускает узел с логами имени агента (start/end/error)."""
    agent_name, agent_role = _agent_identity(agent, fallback=node_name)
    task_id = state["task_id"]
    thread_id = state.get("thread_id", task_id)
    node_metric = f"{node_name}_node"
    circuit = _node_circuit(node_name)
    now = time()
    if circuit.is_open(now):
        retry_after = max(0.0, circuit.open_until - now)
        agent_metrics.record_error(agent_role, "CircuitOpenError")
        logger.warning(
            "agent.node.circuit_open",
            agent=agent_name,
            agent_role=agent_role,
            node=node_name,
            task_id=task_id,
            thread_id=thread_id,
            retry_after_seconds=round(retry_after, 1),
        )
        raise CircuitOpenError(node_name, retry_after_seconds=retry_after)

    logger.debug(
        "agent.node.start",
        agent=agent_name,
        agent_role=agent_role,
        node=node_name,
        task_id=task_id,
        thread_id=thread_id,
    )
    started = perf_counter()
    try:
        update, result = await run()
    except Exception as exc:
        duration_ms = round((perf_counter() - started) * 1000)
        circuit.record_failure(time())
        agent_metrics.record_node_execution(agent_role, node_metric, duration_seconds=duration_ms / 1000.0)
        agent_metrics.record_error(agent_role, type(exc).__name__)
        hop = get_hop_collector()
        if hop is not None:
            hop.record(node=node_name, agent=agent_name, duration_ms=duration_ms, status="error")
        logger.warning(
            "agent.node.error",
            agent=agent_name,
            agent_role=agent_role,
            node=node_name,
            task_id=task_id,
            thread_id=thread_id,
            duration_ms=duration_ms,
            error=str(exc),
            circuit_failures=circuit.consecutive_failures,
        )
        raise
    circuit.record_success()
    duration_ms = round((perf_counter() - started) * 1000)
    result_fields = _result_fields(result)
    agent_metrics.record_node_execution(agent_role, node_metric, duration_seconds=duration_ms / 1000.0)
    hop = get_hop_collector()
    if hop is not None:
        status = result_fields.get("status")
        hop.record(
            node=node_name,
            agent=agent_name,
            duration_ms=duration_ms,
            status=status if isinstance(status, str) else None,
        )
    logger.debug(
        "agent.node.end",
        agent=agent_name,
        agent_role=agent_role,
        node=node_name,
        task_id=task_id,
        thread_id=thread_id,
        duration_ms=duration_ms,
        **result_fields,
    )
    return update


@traceable(name="graph.node.contextualizer")
async def _contextualizer_node(
    state: AgentGraphState,
    agent: ContextualizerAgent,
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
        # Intent has not run yet — invoke rewrite whenever assistant prior exists
        # so Intent receives live continuation_kind (not always-None dead hints).
        task_input = ContextualizerInput(
            task_id=state["task_id"],
            user_text=state["user_text"],
            dialog_window=window,
            memory_hints=memory_hints,
            prompt_budget=budget,
            task_kind=None,
            requires_mcp=False,
        )
        context = AgentContext(thread_id=state.get("thread_id", state["task_id"]))
        result = await agent.execute(task_input, context)
        rewritten = result.output.rewritten_query if result.output is not None else state["user_text"]
        return {
            "contextualization": result,
            "effective_user_text": rewritten,
        }, result

    return await _run_logged_node(agent=agent, node_name="contextualizer", state=state, run=run)


@traceable(name="graph.node.intent_classifier")
async def _intent_classifier_node(
    state: AgentGraphState,
    agent: IntentClassifierAgent,
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
        context = AgentContext(thread_id=state.get("thread_id", state["task_id"]))
        result = await agent.execute(task_input, context)
        routing_intent = ContinuityPolicy.resolve(
            contextualizer=ctx_out,
            dialog=dialog,
            raw_intent=result.output,
        )
        return {
            "classification": result,
            "routing_intent": routing_intent,
        }, result

    return await _run_logged_node(agent=agent, node_name="intent_classifier", state=state, run=run)


@traceable(name="graph.node.supervisor")
async def _supervisor_node(
    state: AgentGraphState,
    agent: SupervisorAgent,
) -> AgentGraphState:
    """Узел LangGraph: роутинг по platform task kind."""

    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_supervisor_input(snapshot)
        context = AgentContext(thread_id=snapshot.thread_id)
        result = await agent.execute(task_input, context)
        return {"routing": result}, result

    return await _run_logged_node(agent=agent, node_name="supervisor", state=state, run=run)


@traceable(name="graph.node.context_weaver")
async def _context_weaver_node(
    state: AgentGraphState,
    agent: ContextWeaverAgent,
) -> AgentGraphState:
    """Узел LangGraph: сборка context bundle и execution plan."""

    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_context_weaver_input(snapshot)
        context = AgentContext(thread_id=snapshot.thread_id)
        result = await agent.execute(task_input, context)
        return {"context_bundle": result}, result

    return await _run_logged_node(agent=agent, node_name="context_weaver", state=state, run=run)


@traceable(name="graph.node.critic")
async def _critic_node(
    state: AgentGraphState,
    agent: CriticAgent,
) -> AgentGraphState:
    """Узел LangGraph: quality gate (LLM-as-a-Judge)."""

    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_critic_input(snapshot, state)
        context = AgentContext(thread_id=snapshot.thread_id)
        result = await agent.execute(task_input, context)
        return {"critic": result}, result

    return await _run_logged_node(agent=agent, node_name="critic", state=state, run=run)


@traceable(name="graph.node.researcher")
async def _researcher_node(
    state: AgentGraphState,
    agent: ResearcherAgent,
) -> AgentGraphState:
    """Узел LangGraph: research worker."""

    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_researcher_input(snapshot, state)
        context = AgentContext(thread_id=snapshot.thread_id)
        result = await agent.execute(task_input, context)
        return {"execution": result}, result

    return await _run_logged_node(agent=agent, node_name="researcher", state=state, run=run)


@traceable(name="graph.node.formatter")
async def _formatter_node(
    state: AgentGraphState,
    agent: FormatterAgent,
) -> AgentGraphState:
    """Узел LangGraph: финальное форматирование ответа."""

    async def run() -> tuple[AgentGraphState, object]:
        snapshot = OrchestrationSnapshot.from_state(state)
        task_input = node_inputs.build_formatter_input(snapshot, state)
        context = AgentContext(thread_id=snapshot.thread_id)
        result = await agent.execute(task_input, context)
        return {"formatted": result}, result

    return await _run_logged_node(agent=agent, node_name="formatter", state=state, run=run)


def _route_after_context(state: AgentGraphState) -> Literal["researcher", "critic"]:
    """Выбирает следующий узел после ContextWeaver."""
    snapshot = OrchestrationSnapshot.from_state(state)
    if snapshot.selected_strategy in WORKER_STRATEGIES:
        return "researcher"
    return "critic"


def build_agent_graph(
    intent_agent: IntentClassifierAgent,
    supervisor_agent: SupervisorAgent,
    context_weaver_agent: ContextWeaverAgent,
    researcher_agent: ResearcherAgent,
    critic_agent: CriticAgent,
    formatter_agent: FormatterAgent,
    contextualizer_agent: ContextualizerAgent,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentGraphState]:
    """Собирает StateGraph с checkpointer (thread-scoped working memory)."""
    graph = StateGraph(AgentGraphState)

    async def contextualizer_node(state: AgentGraphState) -> AgentGraphState:
        return await _contextualizer_node(state, contextualizer_agent)

    async def intent_node(state: AgentGraphState) -> AgentGraphState:
        return await _intent_classifier_node(state, intent_agent)

    async def supervisor_node(state: AgentGraphState) -> AgentGraphState:
        return await _supervisor_node(state, supervisor_agent)

    async def context_weaver_node(state: AgentGraphState) -> AgentGraphState:
        return await _context_weaver_node(state, context_weaver_agent)

    async def researcher_node(state: AgentGraphState) -> AgentGraphState:
        return await _researcher_node(state, researcher_agent)

    async def critic_node(state: AgentGraphState) -> AgentGraphState:
        return await _critic_node(state, critic_agent)

    async def formatter_node(state: AgentGraphState) -> AgentGraphState:
        return await _formatter_node(state, formatter_agent)

    graph.add_node("contextualizer", contextualizer_node)
    graph.add_node("intent_classifier", intent_node)
    graph.add_node("supervisor", supervisor_node)
    graph.add_node("context_weaver", context_weaver_node)
    graph.add_node("researcher", researcher_node)
    graph.add_node("critic", critic_node)
    graph.add_node("formatter", formatter_node)

    graph.add_edge(START, "contextualizer")
    graph.add_edge("contextualizer", "intent_classifier")
    graph.add_edge("intent_classifier", "supervisor")
    graph.add_edge("supervisor", "context_weaver")
    graph.add_conditional_edges("context_weaver", _route_after_context)
    graph.add_edge("researcher", "critic")
    graph.add_edge("critic", "formatter")
    graph.add_edge("formatter", END)
    saver = checkpointer if checkpointer is not None else MemorySaver(serde=build_checkpoint_serde())
    # Mutating MCP tools pause via langgraph.types.interrupt() inside Researcher
    # (finer-grained than compile(interrupt_before=[...])); resume via Command after HITL.
    return graph.compile(checkpointer=saver)
