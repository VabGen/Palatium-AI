# src/palatium_ai/application/agents/critic/config.py

"""Critic AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

CRITIC_CONFIG = AgentConfig(
    name="critic",
    role="critic",
    model_tier="frontier",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=60,
    max_retries=3,
    confidence_threshold=0.7,
)

PASSTHROUGH_ACCURACY = 9
PASSTHROUGH_SAFETY = 10
ACCURACY_REVIEW_THRESHOLD = 6
SAFETY_REVIEW_THRESHOLD = 8
