# src/palatium_ai/core/config/llm/base.py

"""Модуль LLMProviderConfig содержит класс LLMProviderConfig.

Класс LLMProviderConfig используется как базовый класс для конфигурации LLM-провайдеров.
"""

from abc import ABC, abstractmethod

from palatium_ai.core.config.base import BaseConfig


class LLMProviderConfig(BaseConfig, ABC):
    """Базовый класс для конфигурации LLM-провайдеров."""

    provider_name: str = ""

    @abstractmethod
    def get_api_key(self) -> str | None:
        """Возвращает API-ключ (если есть)."""
        ...

    @abstractmethod
    def get_base_url(self) -> str:
        """Возвращает базовый URL (если используется)."""
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        """Возвращает модель по умолчанию для данного провайдера."""
        ...
