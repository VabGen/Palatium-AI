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

LEGACY_GRAPH_NODE_IDS: dict[str, str] = {
    "contextualizer": NODE_CONTEXT_ENRICHER_CONTINUATION,
    "context_weaver": NODE_CONTEXT_ENRICHER_WEAVING,
}

__all__ = [
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
