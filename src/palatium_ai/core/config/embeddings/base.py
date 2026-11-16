# src/palatium_ai/core/config/embeddings/base.py

"""Модуль BaseEmbeddingConfig содержит класс BaseEmbeddingConfig.

Класс BaseEmbeddingConfig используется как базовый класс для конфигурации embeddings-провайдеров.
"""

from abc import ABC, abstractmethod

from pydantic import Field

from palatium_ai.core.config.base import BaseConfig


class EmbeddingProviderConfig(BaseConfig, ABC):
    """Абстрактный конфиг для провайдера эмбеддингов."""

    provider_name: str = ""
    #: Whole-request timeout. Concrete providers override the field with their own
    #: env alias; the base default is what the adapter can rely on (010, 080).
    timeout: int = Field(default=60, gt=0)
    #: Connect timeout, kept separate so a dead gateway fails fast instead of holding
    #: the turn for the whole request budget.
    connect_timeout: int = Field(default=10, gt=0, validation_alias="EMBEDDING_CONNECT_TIMEOUT")

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
