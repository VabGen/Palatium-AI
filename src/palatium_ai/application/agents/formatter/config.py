# src/palatium_ai/application/agents/formatter/config.py

"""Formatter AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

FORMATTER_CONFIG = AgentConfig(
    name="formatter",
    role="formatter",
    model_tier="small",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=60,
    max_retries=3,
    confidence_threshold=0.7,
)

MIN_PIPELINE_CONFIDENCE = 0.7
REVIEW_CONFIDENCE_CAP = 0.5
REPAIR_ERROR_HEAD = 1500
