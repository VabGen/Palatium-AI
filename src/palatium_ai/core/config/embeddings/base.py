# src/palatium_ai/core/config/embeddings/base.py

"""Модуль BaseEmbeddingConfig содержит класс BaseEmbeddingConfig.

Класс BaseEmbeddingConfig используется как базовый класс для конфигурации embeddings-провайдеров.
"""

from abc import ABC, abstractmethod

from palatium_ai.core.config.base import BaseConfig


class EmbeddingProviderConfig(BaseConfig, ABC):
    """Абстрактный конфиг для провайдера эмбеддингов."""

    provider_name: str = ""

    @abstractmethod
    def get_api_key(self) -> str | None:
        """Возвращает API-ключ (если есть)."""
        ...

    @abstractmethod
    def get_base_url(self) -> str:
        """Возвращает базовый URL."""
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        """Возвращает модель эмбеддингов по умолчанию."""
        ...

    @abstractmethod
    def get_dimension(self) -> int:
        """Возвращает размерность вектора (опционально)."""
        ...
