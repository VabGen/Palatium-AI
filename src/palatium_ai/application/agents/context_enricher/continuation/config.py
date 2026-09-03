# src/palatium_ai/application/agents/context_enricher/continuation/config.py

"""Continuation phase AgentConfig (pre-intent, 055)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

CONTEXTUALIZER_CONFIG = AgentConfig(
    name="context_enricher_continuation",
    role="context_enricher",
    model_tier="small",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=45,
    max_retries=2,
    confidence_threshold=0.5,
)

CONTINUATION_CONFIG = CONTEXTUALIZER_CONFIG
