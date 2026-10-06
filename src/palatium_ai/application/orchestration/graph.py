# src/palatium_ai/application/orchestration/graph.py

"""LangGraph StateGraph — Intent → Context enricher → Supervisor → Weaver → Worker → Critic → Formatter.

Agent-agnostic by construction (3.2 / OCP): the node roster arrives as `GraphAgents`
(`agent_registry.py`), this module only compiles nodes and declares the topology.

P0.1 latency: Intent classifies raw text first so Contextualizer receives task_kind and
can skip LLM on social/capability; low-risk strategies skip Critic (see route_after_context).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.orchestration import nodes
from palatium_ai.application.orchestration.agent_registry import GraphAgents, NodeCallable
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
    NODE_PARALLEL_WORKERS,
    NODE_QUALITY_REVISION,
    NODE_RESEARCHER,
    NODE_SUPERVISOR,
    GraphNodeId,
)

if TYPE_CHECKING:
    from langgraph.checkpoint.base import BaseCheckpointSaver
    from langgraph.graph.state import CompiledStateGraph

__all__ = ["build_agent_graph", "reset_node_circuits_for_tests"]


def build_agent_graph(
    agents: GraphAgents,
    *,
    harness: Harness | None = None,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentGraphState]:
    """Собирает StateGraph с checkpointer (thread-scoped working memory).

    Nodes come from the registry (`agents.bindings`); the builder never names an agent,
    so the roster can change without touching this file (3.2). Topology stays here —
    LangGraph needs static edges and conditional paths.
    """
    resolved_harness = harness or Harness()
    graph = StateGraph(AgentGraphState)
    for node, run in agents.bindings(resolved_harness):
        _add_node(graph, node, run)
    _wire_agent_edges(graph)
    saver = checkpointer if checkpointer is not None else MemorySaver()
    return graph.compile(checkpointer=saver)


def _add_node(graph: Any, node: GraphNodeId, run: NodeCallable) -> None:
    """Add one bound node to the graph.

    LangGraph's ``add_node`` overloads cannot bind ``NodeInputT`` for a precisely typed
    node callable (none of them accepts a ``TypedDict`` state), so the call crosses an
    ``Any`` boundary. The registry keeps the strict types; this single helper is the only
    place they are erased — deliberately, not as a blanket ``Any`` on the builder.
    """
    graph.add_node(node, run)


def _wire_agent_edges(graph: Any) -> None:
    """Topology (START → … → END) with the Critic→quality_revision→worker loop.

    ``Any`` for the same reason as `_add_node`: LangGraph's conditional-edge overloads
    cannot be satisfied for a ``TypedDict`` state. The node ids themselves stay typed;
    only the graph handle is dynamic.
    """
    graph.add_edge(START, NODE_INTENT_CLASSIFIER)
    graph.add_edge(NODE_INTENT_CLASSIFIER, NODE_CONTEXT_ENRICHER_CONTINUATION)
    graph.add_edge(NODE_CONTEXT_ENRICHER_CONTINUATION, NODE_SUPERVISOR)
    graph.add_edge(NODE_SUPERVISOR, NODE_CONTEXT_ENRICHER_WEAVING)
    graph.add_conditional_edges(NODE_CONTEXT_ENRICHER_WEAVING, nodes.route_after_context)
    graph.add_edge(NODE_RESEARCHER, NODE_CRITIC)
    graph.add_edge(NODE_CODER, NODE_CRITIC)
    graph.add_edge(NODE_ANALYST, NODE_CRITIC)
    graph.add_edge(NODE_PARALLEL_WORKERS, NODE_CRITIC)
    graph.add_conditional_edges(NODE_CRITIC, nodes.route_after_critic)
    graph.add_conditional_edges(NODE_QUALITY_REVISION, nodes.route_after_quality_revision)
    graph.add_edge(NODE_FORMATTER, END)
