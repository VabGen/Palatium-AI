# src/palatium_ai/domain/llm/models.py

"""Доменные модели для LLM-взаимодействия."""

from typing import Literal, Self, get_args
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from palatium_ai.domain.content.citations import CitationRef

# Provider-neutral structured output mode (maps to OpenAI-compatible response_format).
LLMResponseFormat = Literal["text", "json_object", "json_schema"]

#: Image formats the vision path may forward (ADR 0007). Closed on purpose: a mime the
#: model does not accept is a 400 at the provider boundary, i.e. after cost was paid.
ImageMime = Literal["image/png", "image/jpeg", "image/webp"]
VISION_IMAGE_MIMES: frozenset[str] = frozenset(get_args(ImageMime))


class ImagePart(BaseModel):
    """Reference to an image attachment; bytes stay in the blob store (ADR 0007).

    No base64 and no data URL here: the attachment pipeline already owns storage,
    size limits and the decode guard, and a second copy of the bytes in the message
    contract would leak into logs and traces (020).
    """

    model_config = {"frozen": True}

    attachment_id: UUID
    mime: ImageMime


class ChatMessage(BaseModel):
    """Сообщение в диалоге с LLM."""

    model_config = {"frozen": True}

    role: Literal["system", "user", "assistant", "tool"]
    content: str
    #: Anthropic/LiteLLM prompt-cache hint for static system prefixes (P0.3).
    cache_control: Literal["ephemeral"] | None = None
    #: Images the model should look at (ADR 0007). Additive: text-only callers are
    #: unaffected, and an adapter without vision must reject rather than drop them.
    image_parts: tuple[ImagePart, ...] = ()

    @model_validator(mode="after")
    def _images_only_in_user_messages(self) -> Self:
        """User turns carry the ask; system/assistant images are never legitimate.

        Allowing them would let retrieved or model-generated content smuggle an
        "instruction" image past the point where prompt-injection gates look (020).
        """
        if self.image_parts and self.role != "user":
            msg = "image_parts are only allowed on user messages"
            raise ValueError(msg)
        return self


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
    #: Citations the provider attached to ``content`` (W3a). Empty is the honest
    #: default: most providers report none, and a fabricated anchor is worse than no
    #: anchor when the user clicks it.
    citations: tuple[CitationRef, ...] = ()


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
