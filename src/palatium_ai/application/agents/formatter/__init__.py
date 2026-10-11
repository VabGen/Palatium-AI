# src/palatium_ai/application/agents/formatter/__init__.py

"""Formatter agent package (030) — presentation LLM + mechanical pre-clean."""

from palatium_ai.application.agents.formatter.agent import FormatterAgent
from palatium_ai.application.agents.formatter.cleanup import mechanical_cleanup
from palatium_ai.application.agents.formatter.config import FORMATTER_CONFIG
from palatium_ai.application.agents.formatter.parsing import parse_formatter_document

__all__ = [
    "FORMATTER_CONFIG",
    "FormatterAgent",
    "mechanical_cleanup",
    "parse_formatter_document",
]
