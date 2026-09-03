"""Graph order: Contextualizer precedes Intent so continuation hints are live."""

from __future__ import annotations

from palatium_ai.application.agents.harness import Harness
from palatium_ai.application.agents.intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from palatium_ai.application.orchestration.graph import build_agent_graph
from palatium_ai.core.types.graph_nodes import NODE_CONTEXT_ENRICHER_CONTINUATION
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


def test_graph_edges_contextualizer_before_intent() -> None:
    harness = Harness(llm=FakeLLMPort("{}"))
    graph = build_agent_graph(
        harness=harness,
        intent_agent=IntentClassifierAgent(harness, INTENT_CLASSIFIER_CONFIG),  # type: ignore[arg-type]
        supervisor_agent=make_supervisor_agent(harness),
        continuation_agent=make_continuation_agent(harness=harness),
        weaving_agent=make_weaving_agent(harness=harness),
        researcher_agent=make_researcher_agent(FakeLLMPort("{}"), harness=harness),
        coder_agent=make_coder_agent(harness=harness),
        analyst_agent=make_analyst_agent(harness=harness),
        critic_agent=make_critic_agent(FakeLLMPort("{}")),
        formatter_agent=make_formatter_agent(FakeLLMPort("{}")),
    )
    # LangGraph compiled graph exposes topology via get_graph().
    topo = graph.get_graph()
    edges = {(e.source, e.target) for e in topo.edges}
    assert ("__start__", NODE_CONTEXT_ENRICHER_CONTINUATION) in edges
    assert (NODE_CONTEXT_ENRICHER_CONTINUATION, "intent_classifier") in edges
    assert ("intent_classifier", "supervisor") in edges
    assert ("intent_classifier", NODE_CONTEXT_ENRICHER_CONTINUATION) not in edges
