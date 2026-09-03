# src/palatium_ai/application/orchestration/graph.py

"""LangGraph StateGraph — Context enricher → Intent → Supervisor → Weaver → Worker → Critic → Formatter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.orchestration import nodes
from palatium_ai.application.orchestration.node_runtime import reset_node_circuits_for_tests
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.core.types.graph_nodes import (
    NODE_ANALYST,
    NODE_CODER,
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
    NODE_CRITIC,
    NODE_FORMATTER,
    NODE_INTENT_CLASSIFIER,
    NODE_QUALITY_REVISION,
    NODE_RESEARCHER,
    NODE_SUPERVISOR,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

    from palatium_ai.application.agents.analyst import AnalystAgent
    from palatium_ai.application.agents.coder import CoderAgent
    from palatium_ai.application.agents.context_enricher import ContextualizerAgent, ContextWeaverAgent
    from palatium_ai.application.agents.critic import CriticAgent
    from palatium_ai.application.agents.formatter import FormatterAgent
    from palatium_ai.application.agents.intent_classifier import IntentClassifierAgent
    from palatium_ai.application.agents.researcher import ResearcherAgent
    from palatium_ai.application.agents.supervisor import SupervisorAgent

__all__ = ["build_agent_graph", "reset_node_circuits_for_tests"]


def _bind_node(node_fn: Any, agent: object, harness: Harness) -> Any:
    """Bind agent+harness into a LangGraph node callable (typed Any for StateGraph overloads)."""

    async def _run(state: AgentGraphState) -> AgentGraphState:
        return cast("AgentGraphState", await node_fn(state, agent, harness))

    return _run


def build_agent_graph(
    intent_agent: IntentClassifierAgent,
    supervisor_agent: SupervisorAgent,
    researcher_agent: ResearcherAgent,
    critic_agent: CriticAgent,
    formatter_agent: FormatterAgent,
    *,
    coder_agent: CoderAgent,
    analyst_agent: AnalystAgent,
    continuation_agent: ContextualizerAgent,
    weaving_agent: ContextWeaverAgent,
    harness: Harness | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentGraphState]:
    """Собирает StateGraph с checkpointer (thread-scoped working memory)."""
    resolved_harness = harness or Harness()
    graph = StateGraph(AgentGraphState)
    _register_agent_nodes(
        graph,
        harness=resolved_harness,
        intent_agent=intent_agent,
        supervisor_agent=supervisor_agent,
        researcher_agent=researcher_agent,
        critic_agent=critic_agent,
        formatter_agent=formatter_agent,
        coder_agent=coder_agent,
        analyst_agent=analyst_agent,
        continuation_agent=continuation_agent,
        weaving_agent=weaving_agent,
    )
    _wire_agent_edges(graph)
    saver = checkpointer if checkpointer is not None else MemorySaver()
    return graph.compile(checkpointer=saver)


def _register_agent_nodes(
    graph: Any,
    *,
    harness: Harness,
    intent_agent: IntentClassifierAgent,
    supervisor_agent: SupervisorAgent,
    researcher_agent: ResearcherAgent,
    critic_agent: CriticAgent,
    formatter_agent: FormatterAgent,
    coder_agent: CoderAgent,
    analyst_agent: AnalystAgent,
    continuation_agent: ContextualizerAgent,
    weaving_agent: ContextWeaverAgent,
) -> None:
    graph.add_node(
        NODE_CONTEXT_ENRICHER_CONTINUATION,
        _bind_node(nodes.continuation_node, continuation_agent, harness),
    )
    graph.add_node(NODE_INTENT_CLASSIFIER, _bind_node(nodes.intent_classifier_node, intent_agent, harness))
    graph.add_node(NODE_SUPERVISOR, _bind_node(nodes.supervisor_node, supervisor_agent, harness))
    graph.add_node(
        NODE_CONTEXT_ENRICHER_WEAVING,
        _bind_node(nodes.weaving_node, weaving_agent, harness),
    )
    graph.add_node(NODE_RESEARCHER, _bind_node(nodes.researcher_node, researcher_agent, harness))
    graph.add_node(NODE_CODER, _bind_node(nodes.coder_node, coder_agent, harness))
    graph.add_node(NODE_ANALYST, _bind_node(nodes.analyst_node, analyst_agent, harness))
    graph.add_node(NODE_CRITIC, _bind_node(nodes.critic_node, critic_agent, harness))
    graph.add_node(NODE_QUALITY_REVISION, nodes.quality_revision_node)
    graph.add_node(NODE_FORMATTER, _bind_node(nodes.formatter_node, formatter_agent, harness))


def _wire_agent_edges(graph: Any) -> None:
    graph.add_edge(START, NODE_CONTEXT_ENRICHER_CONTINUATION)
    graph.add_edge(NODE_CONTEXT_ENRICHER_CONTINUATION, NODE_INTENT_CLASSIFIER)
    graph.add_edge(NODE_INTENT_CLASSIFIER, NODE_SUPERVISOR)
    graph.add_edge(NODE_SUPERVISOR, NODE_CONTEXT_ENRICHER_WEAVING)
    graph.add_conditional_edges(NODE_CONTEXT_ENRICHER_WEAVING, nodes.route_after_context)
    graph.add_edge(NODE_RESEARCHER, NODE_CRITIC)
    graph.add_edge(NODE_CODER, NODE_CRITIC)
    graph.add_edge(NODE_ANALYST, NODE_CRITIC)
    graph.add_conditional_edges(NODE_CRITIC, nodes.route_after_critic)
    graph.add_conditional_edges(NODE_QUALITY_REVISION, nodes.route_after_quality_revision)
    graph.add_edge(NODE_FORMATTER, END)
