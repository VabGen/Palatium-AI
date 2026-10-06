# src/palatium_ai/application/orchestration/agent_registry.py

"""Agent-graph registry — the single mapping of agents to graph nodes (rules 000 / 030 / 065).

`graph.py` compiles whatever this module binds and never names an agent: adding or
replacing an agent is an edit to `GraphAgents` (+ its own package), not to the builder,
its edges or its call sites (OCP).

Contract notes:
- node ids come from `core/types/graph_nodes.py` (single source of truth) and are typed
  as `GraphNodeId`, so a typo fails type-check, not graph compilation;
- `bind_agent` type-checks the agent↔node-function pairing (the old `Any`-typed helper
  accepted a `FormatterAgent` bound to the critic node silently);
- the agentless step (`quality_revision`) goes through `bind_plain_node` — one code path
  for both cases, no special case in the builder.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from palatium_ai.application.agents.analyst import AnalystAgent
from palatium_ai.application.agents.coder import CoderAgent
from palatium_ai.application.agents.context_enricher import ContextualizerAgent, ContextWeaverAgent
from palatium_ai.application.agents.critic import CriticAgent
from palatium_ai.application.agents.formatter import FormatterAgent
from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import IntentClassifierAgent
from palatium_ai.application.agents.researcher import ResearcherAgent
from palatium_ai.application.agents.supervisor import SupervisorAgent
from palatium_ai.application.orchestration import nodes
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
from palatium_ai.domain.agents.base import BaseAgent

__all__ = ["BoundNode", "GraphAgents", "NodeCallable", "bind_agent", "bind_plain_node"]

type NodeCallable = Callable[[AgentGraphState], Awaitable[AgentGraphState]]
#: ``(node id, bound callable)`` — what `graph.py` feeds to `StateGraph.add_node`.
type BoundNode = tuple[GraphNodeId, NodeCallable]


def bind_agent[TAgent: BaseAgent](
    node: GraphNodeId,
    agent: TAgent,
    run: Callable[[AgentGraphState, TAgent, Harness], Awaitable[AgentGraphState]],
    harness: Harness,
) -> BoundNode:
    """Bind one agent + harness into a LangGraph node callable (pairing is type-checked)."""

    async def _run(state: AgentGraphState) -> AgentGraphState:
        return await run(state, agent, harness)

    return (node, _run)


def bind_plain_node(node: GraphNodeId, run: NodeCallable) -> BoundNode:
    """Bind an agentless node (pure state transition, e.g. the quality-revision step)."""
    return (node, run)


@dataclass(frozen=True)
class GraphAgents:
    """Roster of the agents in the compiled graph — the agent registry of 3.2.

    Frozen value object: assembled by the composition root (`application/wiring.py`),
    consumed by `build_agent_graph`. Keeping construction in the composition root is
    deliberate (000) — agents need infrastructure-backed deps (MCP registry, LLM
    factory), and `application/orchestration` must not import `infrastructure`.
    """

    intent_agent: IntentClassifierAgent
    supervisor_agent: SupervisorAgent
    researcher_agent: ResearcherAgent
    critic_agent: CriticAgent
    formatter_agent: FormatterAgent
    coder_agent: CoderAgent
    analyst_agent: AnalystAgent
    continuation_agent: ContextualizerAgent
    weaving_agent: ContextWeaverAgent

    def bindings(self, harness: Harness) -> tuple[BoundNode, ...]:
        """Node id → bound node callable, in graph order (the registry table).

        Adding an agent (the point of 3.2):
        1. its own package `application/agents/<name>/` (030);
        2. a node function in `orchestration/nodes.py` — agent-specific state mapping
           (AgentGraphState → AgentInput → AgentGraphState), the one thing the builder
           cannot derive (065 keeps that glue next to the state definition, not in the
           agent package);
        3. a field on `GraphAgents` + one row below;
        4. an edge in `graph._wire_agent_edges` — only if the *topology* changes, since
           LangGraph needs static edges/conditions.

        No change to `application/wiring.py` call shape or `graph.py` builder.
        """
        return (
            bind_agent(NODE_INTENT_CLASSIFIER, self.intent_agent, nodes.intent_classifier_node, harness),
            bind_agent(
                NODE_CONTEXT_ENRICHER_CONTINUATION,
                self.continuation_agent,
                nodes.continuation_node,
                harness,
            ),
            bind_agent(NODE_SUPERVISOR, self.supervisor_agent, nodes.supervisor_node, harness),
            bind_agent(
                NODE_CONTEXT_ENRICHER_WEAVING,
                self.weaving_agent,
                nodes.weaving_node,
                harness,
            ),
            bind_agent(NODE_RESEARCHER, self.researcher_agent, nodes.researcher_node, harness),
            bind_agent(NODE_CODER, self.coder_agent, nodes.coder_node, harness),
            bind_agent(NODE_ANALYST, self.analyst_agent, nodes.analyst_node, harness),
            self._bind_parallel_workers(harness),
            bind_agent(NODE_CRITIC, self.critic_agent, nodes.critic_node, harness),
            bind_plain_node(NODE_QUALITY_REVISION, nodes.quality_revision_node),
            bind_agent(NODE_FORMATTER, self.formatter_agent, nodes.formatter_node, harness),
        )

    def _bind_parallel_workers(self, harness: Harness) -> BoundNode:
        """Fan-out node shares researcher + analyst agents (P2.15)."""
        researcher = self.researcher_agent
        analyst = self.analyst_agent

        async def _run(state: AgentGraphState) -> AgentGraphState:
            return await nodes.parallel_workers_node(state, researcher, analyst, harness)

        return (NODE_PARALLEL_WORKERS, _run)
