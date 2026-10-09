# src/palatium_ai/domain/llm/models.py

"""Доменные модели для LLM-взаимодействия."""

from typing import Literal

from pydantic import BaseModel, Field

# Provider-neutral structured output mode (maps to OpenAI-compatible response_format).
LLMResponseFormat = Literal["text", "json_object", "json_schema"]


class ChatMessage(BaseModel):
    """Сообщение в диалоге с LLM."""

    model_config = {"frozen": True}

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    #: Anthropic/LiteLLM prompt-cache hint for static system prefixes (P0.3).
    cache_control: Literal["ephemeral"] | None = None


class LLMUsage(BaseModel):
    """Статистика использования токенов."""

    model_config = {"frozen": True}

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LLMCompletion(BaseModel):
    """Результат синхронной генерации текста."""

    model_config = {"frozen": True}

    content: str
    model: str
    usage: LLMUsage = Field(default_factory=LLMUsage)
    finish_reason: str | None = None
    # Cost reported by the provider/gateway for this call (USD), or None when it reports none.
    # A gateway that routes opaque tier aliases (``tier-small`` → real model) is the ONLY
    # component that can price the call, so this is authoritative over any local price table.
    cost_usd: float | None = Field(default=None, ge=0.0)


class LLMStreamDelta(BaseModel):
    """Фрагмент потоковой генерации.

    Trailing chunks may carry usage/cost when the provider was asked for
    ``stream_options.include_usage`` (OpenAI-compatible / LiteLLM).
    """

    model_config = {"frozen": True}

    content: str = ""
    finish_reason: str | None = None
    usage: LLMUsage | None = None
    cost_usd: float | None = Field(default=None, ge=0.0)
    model: str | None = None
