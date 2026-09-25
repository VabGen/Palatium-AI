# src/palatium_ai/core/types/graph_nodes.py

"""Canonical LangGraph node ids (topology, metrics, checkpoint migration)."""

from __future__ import annotations

from typing import Final, Literal

NODE_CONTEXT_ENRICHER_CONTINUATION: Final[Literal["context_enricher_continuation"]] = "context_enricher_continuation"
NODE_CONTEXT_ENRICHER_WEAVING: Final[Literal["context_enricher_weaving"]] = "context_enricher_weaving"
NODE_INTENT_CLASSIFIER: Final[Literal["intent_classifier"]] = "intent_classifier"
NODE_SUPERVISOR: Final[Literal["supervisor"]] = "supervisor"
NODE_RESEARCHER: Final[Literal["researcher"]] = "researcher"
NODE_CODER: Final[Literal["coder"]] = "coder"
NODE_ANALYST: Final[Literal["analyst"]] = "analyst"
NODE_CRITIC: Final[Literal["critic"]] = "critic"
NODE_QUALITY_REVISION: Final[Literal["quality_revision"]] = "quality_revision"
NODE_FORMATTER: Final[Literal["formatter"]] = "formatter"

#: Union of every node id — lets the registry declare `node: GraphNodeId` and catch a
#: typo'd node id at type-check time instead of at graph-compile time (010).
type GraphNodeId = Literal[
    "context_enricher_continuation",
    "context_enricher_weaving",
    "intent_classifier",
    "supervisor",
    "researcher",
    "coder",
    "analyst",
    "critic",
    "quality_revision",
    "formatter",
]

LEGACY_GRAPH_NODE_IDS: dict[str, str] = {
    "contextualizer": NODE_CONTEXT_ENRICHER_CONTINUATION,
    "context_weaver": NODE_CONTEXT_ENRICHER_WEAVING,
}

#: Runtime list of every node id. Deliberately a second, *checked* copy of the Literal
#: above: the Literal is the type-level source, this tuple the runtime one — a unit test
#: asserts they agree (`tests/unit/test_agent_registry.py`), so they cannot drift (010).
GRAPH_NODE_IDS: Final[tuple[GraphNodeId, ...]] = (
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_CONTEXT_ENRICHER_WEAVING,
    NODE_INTENT_CLASSIFIER,
    NODE_SUPERVISOR,
    NODE_RESEARCHER,
    NODE_CODER,
    NODE_ANALYST,
    NODE_CRITIC,
    NODE_QUALITY_REVISION,
    NODE_FORMATTER,
)

__all__ = [
    "GRAPH_NODE_IDS",
    "GraphNodeId",
    "LEGACY_GRAPH_NODE_IDS",
    "NODE_CONTEXT_ENRICHER_CONTINUATION",
    "NODE_CONTEXT_ENRICHER_WEAVING",
    "NODE_ANALYST",
    "NODE_CODER",
    "NODE_CRITIC",
    "NODE_FORMATTER",
    "NODE_INTENT_CLASSIFIER",
    "NODE_QUALITY_REVISION",
    "NODE_RESEARCHER",
    "NODE_SUPERVISOR",
]
