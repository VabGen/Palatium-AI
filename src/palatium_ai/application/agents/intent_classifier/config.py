# src/palatium_ai/application/agents/intent_classifier/config.py

"""IntentClassifier AgentConfig (030)."""

from palatium_ai.domain.agents.agent_config import AgentConfig

INTENT_CLASSIFIER_CONFIG = AgentConfig(
    name="intent_classifier",
    role="intent_classifier",
    model_tier="small",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=60,
    max_retries=3,
    confidence_threshold=0.7,
)
