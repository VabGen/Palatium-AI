# palatium_ai/domain/__init__.py

"""Доменный слой: контракты агентов и порты.

Не импортируем ports/mcp здесь: иначе любой import domain.* тянет mcp.models
и замыкает цикл через policies → agents.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .ports import EmbeddingPort, LLMPort

__all__ = ["LLMPort", "EmbeddingPort"]


def __getattr__(name: str) -> Any:
    if name in {"LLMPort", "EmbeddingPort"}:
        from .ports import EmbeddingPort, LLMPort

        mapping = {"LLMPort": LLMPort, "EmbeddingPort": EmbeddingPort}
        value = mapping[name]
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
