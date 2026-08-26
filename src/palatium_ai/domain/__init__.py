# palatium_ai/domain/__init__.py

"""Доменный слой: контракты агентов и порты."""

from .ports import EmbeddingPort, LLMPort

__all__ = ["LLMPort", "EmbeddingPort"]
