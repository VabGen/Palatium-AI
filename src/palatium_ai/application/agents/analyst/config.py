# src/palatium_ai/application/agents/analyst/config.py

"""Analyst AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

ANALYST_CONFIG = AgentConfig(
    name="analyst",
    role="analyst",
    model_tier="mid",
    temperature=0.1,
    allowed_tools=(),
    timeout_seconds=90,
    max_retries=2,
    confidence_threshold=0.7,
)
