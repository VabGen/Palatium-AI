# src/palatium_ai/application/agents/context_enricher/weaving/config.py

"""Weaving phase AgentConfig (post-supervisor execution plan, 055)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

CONTEXT_WEAVER_CONFIG = AgentConfig(
    name="context_enricher_weaving",
    role="context_enricher",
    model_tier="small",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=30,
    max_retries=1,
    confidence_threshold=0.7,
)

WEAVING_CONFIG = CONTEXT_WEAVER_CONFIG
PLANNED_CONFIDENCE = 1.0
CLARIFY_CONFIDENCE = 0.5
