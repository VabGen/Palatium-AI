# src/palatium_ai/application/agents/context_enricher/__init__.py

"""Context enricher — continuation (pre-intent) + weaving (post-supervisor) phases (055)."""

from palatium_ai.application.agents.context_enricher.continuation import (
    CONTEXTUALIZER_CONFIG,
    CONTINUATION_CONFIG,
    ContextualizerAgent,
)
from palatium_ai.application.agents.context_enricher.weaving import (
    CONTEXT_WEAVER_CONFIG,
    WEAVING_CONFIG,
    ContextWeaverAgent,
)

__all__ = [
    "CONTEXTUALIZER_CONFIG",
    "CONTEXT_WEAVER_CONFIG",
    "CONTINUATION_CONFIG",
    "WEAVING_CONFIG",
    "ContextWeaverAgent",
    "ContextualizerAgent",
]
