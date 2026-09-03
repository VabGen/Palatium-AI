# src/palatium_ai/application/agents/text_ingestor/__init__.py

"""TextIngestor agent package (030, planned — off LangGraph hot path)."""

from palatium_ai.application.agents.text_ingestor.agent import TextIngestorAgent
from palatium_ai.application.agents.text_ingestor.config import TEXT_INGESTOR_CONFIG

__all__ = ["TEXT_INGESTOR_CONFIG", "TextIngestorAgent"]
