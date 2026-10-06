# tests/unit/test_agent_registry.py

"""Agent registry ↔ graph contract (3.2 / OCP).

`GraphAgents` is the single place mapping agents to graph nodes (rules 000 / 030 / 065).
These checks keep the registry, the canonical node ids (`core/types/graph_nodes.py`) and
the compiled graph in sync: adding or replacing an agent is a registry edit — not a
`graph.py` edit — and a half-done registration fails here instead of at runtime.
"""

from __future__ import annotations

import inspect

from typing import get_args

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.agent_registry import GraphAgents
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.core.types.graph_nodes import GRAPH_NODE_IDS, GraphNodeId
from tests.conftest import (
    FakeLLMPort,
    make_analyst_agent,
    make_coder_agent,
    make_continuation_agent,
    make_critic_agent,
    make_formatter_agent,
    make_researcher_agent,
    make_supervisor_agent,
    make_weaving_agent,
)


def _harness() -> Harness:
    return Harness(llm=FakeLLMPort("{}"))


def _roster(harness: Harness) -> GraphAgents:
    """Full roster built from fakes — the shape `application/wiring.py` supplies in prod."""
    return GraphAgents(
        intent_agent=IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG),  # type: ignore[arg-type]
        supervisor_agent=make_supervisor_agent(harness),  # type: ignore[arg-type]
        researcher_agent=make_researcher_agent(FakeLLMPort("{}"), harness=harness),  # type: ignore[arg-type]
        critic_agent=make_critic_agent(FakeLLMPort("{}")),  # type: ignore[arg-type]
        formatter_agent=make_formatter_agent(FakeLLMPort("{}")),  # type: ignore[arg-type]
        coder_agent=make_coder_agent(harness=harness),  # type: ignore[arg-type]
        analyst_agent=make_analyst_agent(harness=harness),  # type: ignore[arg-type]
        continuation_agent=make_continuation_agent(harness=harness),  # type: ignore[arg-type]
        weaving_agent=make_weaving_agent(harness=harness),  # type: ignore[arg-type]
    )


def test_registry_binds_every_canonical_node_once() -> None:
    """Registry node ids are unique and cover exactly the canonical node-id set."""
    harness = _harness()
    bound = [node for node, _ in _roster(harness).bindings(harness)]

    assert len(bound) == len(set(bound)), f"duplicate node id in registry: {bound}"
    assert set(bound) == set(GRAPH_NODE_IDS), (
        "registry and core/types/graph_nodes.py diverged — a node id exists in one but not "
        "the other (add the constant and the registry row together)"
    )


def test_registry_entries_are_async_node_callables() -> None:
    """Every entry is an async callable of the graph state (LangGraph node contract)."""
    harness = _harness()
    for node, run in _roster(harness).bindings(harness):
        assert inspect.iscoroutinefunction(run), f"{node} is not bound to an async node callable"


def test_compiled_graph_nodes_match_registry() -> None:
    """`build_agent_graph` registers exactly the registry nodes (no silent drops or extras)."""
    harness = _harness()
    graph = build_agent_graph(_roster(harness), harness=harness)

    compiled = {name for name in graph.get_graph().nodes if name not in {"__start__", "__end__"}}
    assert compiled == set(GRAPH_NODE_IDS)


def test_graph_node_id_literal_matches_runtime_tuple() -> None:
    """The `GraphNodeId` Literal and the runtime `GRAPH_NODE_IDS` tuple cannot drift (010)."""
    literal_members = set(get_args(GraphNodeId.__value__))

    assert literal_members == set(GRAPH_NODE_IDS)


def test_builder_takes_roster_not_per_agent_arguments() -> None:
    """`build_agent_graph` accepts the registry, not one argument per agent (OCP guard)."""
    parameters = inspect.signature(build_agent_graph).parameters

    assert next(iter(parameters)) == "agents"
    assert set(list(parameters)[1:]) == {"harness", "checkpointer"}
    assert not any(name.endswith("_agent") for name in parameters), (
        "per-agent builder arguments are back — new agents would again require editing graph.py"
    )
