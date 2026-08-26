"""Graph order: Contextualizer precedes Intent so continuation hints are live."""

from __future__ import annotations

from palatium_ai.application.agents.context_weaver_agent import ContextWeaverAgent
from palatium_ai.application.agents.contextualizer_agent import ContextualizerAgent
from palatium_ai.application.agents.critic_agent import CriticAgent
from palatium_ai.application.agents.formatter_agent import FormatterAgent
from palatium_ai.application.agents.intent_classifier_agent import IntentClassifierAgent
from palatium_ai.application.agents.researcher_agent import ResearcherAgent
from palatium_ai.application.agents.supervisor_agent import SupervisorAgent
from palatium_ai.application.orchestration.graph import build_agent_graph
from tests.conftest import FakeLLMPort


def test_graph_edges_contextualizer_before_intent() -> None:
    graph = build_agent_graph(
        intent_agent=IntentClassifierAgent(FakeLLMPort("{}")),
        supervisor_agent=SupervisorAgent(),
        context_weaver_agent=ContextWeaverAgent(),
        researcher_agent=ResearcherAgent(FakeLLMPort("{}")),
        critic_agent=CriticAgent(FakeLLMPort("{}")),
        formatter_agent=FormatterAgent(FakeLLMPort("{}")),
        contextualizer_agent=ContextualizerAgent(FakeLLMPort("{}")),
    )
    # LangGraph compiled graph exposes topology via get_graph().
    topo = graph.get_graph()
    edges = {(e.source, e.target) for e in topo.edges}
    assert ("__start__", "contextualizer") in edges
    assert ("contextualizer", "intent_classifier") in edges
    assert ("intent_classifier", "supervisor") in edges
    assert ("intent_classifier", "contextualizer") not in edges
