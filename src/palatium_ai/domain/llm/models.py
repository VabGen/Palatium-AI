# src/palatium_ai/domain/llm/models.py

"""Доменные модели для LLM-взаимодействия."""

from typing import Literal

from pydantic import BaseModel, Field

# Provider-neutral structured output mode (maps to OpenAI-compatible response_format).
LLMResponseFormat = Literal["text", "json_object"]


class ChatMessage(BaseModel):
    """Сообщение в диалоге с LLM."""

    model_config = {"frozen": True}

    role: Literal["system", "user", "assistant", "tool"]
    content: str


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


class LLMStreamDelta(BaseModel):
    """Фрагмент потоковой генерации."""

    model_config = {"frozen": True}

    content: str = ""
    finish_reason: str | None = None
