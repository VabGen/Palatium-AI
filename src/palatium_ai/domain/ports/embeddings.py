# src/palatium_ai/domain/ports/embeddings.py

"""Порт доступа к embedding-провайдерам."""

from typing import Protocol


class EmbeddingPort(Protocol):
    """Контракт получения векторных представлений текста."""

    async def embed(
        self,
        texts: list[str],
        *,
        model: str | None = None,
    ) -> list[list[float]]:
        """Преобразует тексты в векторы."""
        ...
