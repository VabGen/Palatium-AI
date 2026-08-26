# src/palatium_ai/core/config/llm/ollama.py

"""Модуль OllamaLLMConfig содержит класс OllamaLLMConfig.

Класс OllamaLLMConfig используется для конфигурирования LLM-провайдера Ollama.
"""

from pydantic import Field, SecretStr, field_validator

from palatium_ai.core.config.base import validate_base_url

from .base import LLMProviderConfig


class OllamaLLMConfig(LLMProviderConfig):
    """Настройки Ollama."""

    provider_name: str = "ollama"
    api_key: SecretStr | None = Field(
        default=None,
        validation_alias="OLLAMA_API_KEY",
    )

    base_url: str = Field(
        default="http://localhost:11434",
        validation_alias="OLLAMA_BASE_URL",
    )
    default_model: str = Field(
        default="llama3.2",
        validation_alias="OLLAMA_DEFAULT_MODEL",
    )
    timeout: int = Field(default=120, validation_alias="OLLAMA_TIMEOUT")
    num_predict: int = Field(default=4096, validation_alias="OLLAMA_NUM_PREDICT")
    temperature: float = Field(default=0.1, validation_alias="OLLAMA_TEMPERATURE")

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Проверяет, что URL Ollama корректный."""
        return validate_base_url(v, "Ollama")

    def get_api_key(self) -> str | None:
        """Возвращает API-ключ Ollama."""
        return self.api_key.get_secret_value() if self.api_key else None

    def get_base_url(self) -> str:
        """Возвращает базовый URL Ollama."""
        return self.base_url

    def get_default_model(self) -> str:
        """Возвращает дефолтную модель Ollama."""
        return self.default_model
