# src/palatium_ai/application/agents/supervisor/config.py

"""Supervisor AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

SUPERVISOR_CONFIG = AgentConfig(
    name="supervisor",
    role="supervisor",
    model_tier="mid",
    temperature=0.2,
    allowed_tools=(),
    timeout_seconds=60,
    max_retries=2,
    confidence_threshold=0.7,
)
