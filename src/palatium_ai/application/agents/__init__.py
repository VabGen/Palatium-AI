# src/palatium_ai/application/agents/__init__.py

"""Application agents used by the orchestration graph."""

from .analyst import ANALYST_CONFIG, AnalystAgent
from .coder import CODER_CONFIG, CoderAgent
from .context_enricher import (
    CONTEXT_WEAVER_CONFIG,
    CONTEXTUALIZER_CONFIG,
    CONTINUATION_CONFIG,
    WEAVING_CONFIG,
    ContextualizerAgent,
    ContextWeaverAgent,
)
from .critic import CRITIC_CONFIG, CriticAgent
from .formatter import FORMATTER_CONFIG, FormatterAgent
from .intent_classifier import INTENT_CLASSIFIER_CONFIG, IntentClassifierAgent
from .memory_keeper import MEMORY_KEEPER_CONFIG, MemoryKeeperAgent
from .researcher import RESEARCHER_CONFIG, ResearcherAgent
from .supervisor import SUPERVISOR_CONFIG, SupervisorAgent
from .text_ingestor import TEXT_INGESTOR_CONFIG, TextIngestorAgent

__all__ = [
    "ANALYST_CONFIG",
    "AnalystAgent",
    "CODER_CONFIG",
    "CoderAgent",
    "CONTINUATION_CONFIG",
    "CONTEXTUALIZER_CONFIG",
    "ContextualizerAgent",
    "CONTEXT_WEAVER_CONFIG",
    "ContextWeaverAgent",
    "WEAVING_CONFIG",
    "INTENT_CLASSIFIER_CONFIG",
    "IntentClassifierAgent",
    "SUPERVISOR_CONFIG",
    "SupervisorAgent",
    "RESEARCHER_CONFIG",
    "ResearcherAgent",
    "CRITIC_CONFIG",
    "CriticAgent",
    "FORMATTER_CONFIG",
    "FormatterAgent",
    "MEMORY_KEEPER_CONFIG",
    "MemoryKeeperAgent",
    "TEXT_INGESTOR_CONFIG",
    "TextIngestorAgent",
]
