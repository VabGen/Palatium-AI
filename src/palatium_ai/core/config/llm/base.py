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

    def get_timeout_seconds(self) -> float | None:
        """Per-provider request timeout (seconds); ``None`` → provider/LiteLLM default.

        Concrete providers declare a ``timeout`` field; the adapter must forward it so the
        configured value is not dead config (050, 020).
        """
        raw = getattr(self, "timeout", None)
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return float(raw)
        return None
