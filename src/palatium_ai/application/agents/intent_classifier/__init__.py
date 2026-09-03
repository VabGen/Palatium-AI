# src/palatium_ai/application/agents/intent_classifier/__init__.py

"""Intent classifier agent package (030)."""

from palatium_ai.application.agents.intent_classifier.agent import IntentClassifierAgent
from palatium_ai.application.agents.intent_classifier.config import INTENT_CLASSIFIER_CONFIG

__all__ = ["INTENT_CLASSIFIER_CONFIG", "IntentClassifierAgent"]
