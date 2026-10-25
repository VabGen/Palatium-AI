# src/palatium_ai/core/config/llm/__init__.py

"""Модуль для настроек LLM."""

from __future__ import annotations

from typing import Literal, NamedTuple, cast

from pydantic import Field, model_validator

from palatium_ai.core.config.base import BaseConfig
from palatium_ai.core.config.llm.gateway import GatewayLLMConfig

from .anthropic import AnthropicLLMConfig
from .base import LLMProviderConfig
from .ollama import OllamaLLMConfig
from .openai import OpenAILLMConfig
from .qwen import QwenLLMConfig

LLMProviderName = Literal["openai", "anthropic", "ollama", "qwen", "gateway"]
_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "ollama", "qwen", "gateway"})
ModelTierName = Literal["nano", "small", "mid", "frontier", "deep_reasoning"]

#: Vision payload cap (ADR 0007): 10 MiB is inside every supported provider's limit
#: while staying above a phone photo; the intake cap is separate and larger.
_DEFAULT_VISION_MAX_IMAGE_BYTES = 10 * 1024 * 1024
#: Images per chat call. A turn asking about a handful of files is normal; a whole
#: gallery is a cost spike, and vision tokens are priced per image (080).
_DEFAULT_VISION_MAX_IMAGES = 4


class TierBinding(NamedTuple):
    """Resolved provider + model for one AgentConfig.model_tier."""

    provider: LLMProviderName | None
    model: str | None


class LLMConfig(BaseConfig):
    """Агрегатор всех конфигураций LLM-провайдеров."""

    openai: OpenAILLMConfig = Field(default_factory=OpenAILLMConfig)
    anthropic: AnthropicLLMConfig = Field(default_factory=AnthropicLLMConfig)
    ollama: OllamaLLMConfig = Field(default_factory=OllamaLLMConfig)
    qwen: QwenLLMConfig = Field(default_factory=QwenLLMConfig)
    gateway: GatewayLLMConfig = Field(default_factory=GatewayLLMConfig)

    tier_nano_provider: str | None = Field(default=None, validation_alias="LLM_TIER_NANO_PROVIDER")
    tier_small_provider: str | None = Field(default=None, validation_alias="LLM_TIER_SMALL_PROVIDER")
    tier_mid_provider: str | None = Field(default=None, validation_alias="LLM_TIER_MID_PROVIDER")
    tier_frontier_provider: str | None = Field(
        default=None,
        validation_alias="LLM_TIER_FRONTIER_PROVIDER",
    )
    tier_deep_reasoning_provider: str | None = Field(
        default=None,
        validation_alias="LLM_TIER_DEEP_REASONING_PROVIDER",
    )

    tier_nano_model: str | None = Field(default=None, validation_alias="LLM_TIER_NANO_MODEL")
    tier_small_model: str | None = Field(default=None, validation_alias="LLM_TIER_SMALL_MODEL")
    tier_mid_model: str | None = Field(default=None, validation_alias="LLM_TIER_MID_MODEL")
    tier_frontier_model: str | None = Field(default=None, validation_alias="LLM_TIER_FRONTIER_MODEL")
    tier_deep_reasoning_model: str | None = Field(
        default=None,
        validation_alias="LLM_TIER_DEEP_REASONING_MODEL",
    )

    default_provider: str = Field(
        default="openai",
        validation_alias="LLM_DEFAULT_PROVIDER",
    )
    fallback_providers: str = Field(
        default="",
        validation_alias="LLM_FALLBACK_PROVIDERS",
        description="Comma-separated ordered fallback providers (distinct from primary).",
    )
    vision_model: str | None = Field(
        default=None,
        validation_alias="LLM_VISION_MODEL",
        description=(
            "Vision-capable model alias for chat image parts (ADR 0007). Empty disables "
            "the route (fail-closed). Not a tier: an image call never inherits the "
            "agent's text model, and it never fails over to a text-only provider."
        ),
    )
    vision_max_image_bytes: int = Field(
        default=_DEFAULT_VISION_MAX_IMAGE_BYTES,
        ge=64 * 1024,
        le=64 * 1024 * 1024,
        validation_alias="LLM_VISION_MAX_IMAGE_BYTES",
    )
    vision_max_images: int = Field(
        default=_DEFAULT_VISION_MAX_IMAGES,
        ge=1,
        le=20,
        validation_alias="LLM_VISION_MAX_IMAGES",
    )
    allow_pii_images: bool = Field(
        default=False,
        validation_alias="ALLOW_PII_IMAGES",
        description=(
            "Owner opt-in (default off) to forward PII-flagged images to the vision gateway "
            "(ADR 0007, 020/060). Off keeps the fail-closed denial. On still logs a warning, "
            "counts the image and emits the gen_ai.pii_image_allowed span event on every "
            "forwarded image, so the exception is auditable rather than invisible."
        ),
    )

    @property
    def vision_configured(self) -> bool:
        """True when a vision alias is set; each image is still gated by the policy."""
        return bool((self.vision_model or "").strip())

    @property
    def resolved_vision_model(self) -> str | None:
        """Stripped alias or ``None`` (one normalisation point for every caller)."""
        alias = (self.vision_model or "").strip()
        return alias or None

    @property
    def fallback_provider_list(self) -> tuple[str, ...]:
        """Parsed ordered fallback provider names (unsupported names dropped)."""
        names: list[str] = []
        for raw in self.fallback_providers.split(","):
            name = raw.strip().lower()
            if name and name in _SUPPORTED_PROVIDERS and name not in names:
                names.append(name)
        return tuple(names)

    def build_provider_chain(self, primary: str) -> tuple[str, ...]:
        """Ordered unique provider chain: primary then configured fallbacks."""
        chain: list[str] = []
        for name in (primary, *self.fallback_provider_list):
            cleaned = name.strip().lower()
            if cleaned in _SUPPORTED_PROVIDERS and cleaned not in chain:
                chain.append(cleaned)
        return tuple(chain)

    @model_validator(mode="after")
    def validate_providers(self) -> LLMConfig:
        """Проверяет default и per-tier provider names."""
        if self.default_provider not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"Unknown default_provider: {self.default_provider}")

        provider = getattr(self, self.default_provider)
        if isinstance(provider, (OpenAILLMConfig, AnthropicLLMConfig, QwenLLMConfig)) and provider.api_key is None:
            raise ValueError(f"API key for {self.default_provider} is not set")

        for tier in ("nano", "small", "mid", "frontier", "deep_reasoning"):
            raw = getattr(self, f"tier_{tier}_provider")
            if raw is None or str(raw).strip() == "":
                continue
            name = str(raw).strip()
            if name not in _SUPPORTED_PROVIDERS:
                raise ValueError(f"Unknown LLM_TIER_{tier.upper()}_PROVIDER: {name}")

        for name in self.fallback_provider_list:
            if name not in _SUPPORTED_PROVIDERS:
                raise ValueError(f"Unknown LLM_FALLBACK_PROVIDERS entry: {name}")

        return self

    def get_active_provider(self) -> LLMProviderConfig:
        """Возвращает конфигурацию активного провайдера."""
        return cast("LLMProviderConfig", getattr(self, self.default_provider))

    def resolve_tier_binding(self, tier: str) -> TierBinding:
        """Map AgentConfig.model_tier → optional (provider, model) from Settings."""
        provider_map: dict[str, str | None] = {
            "nano": self.tier_nano_provider,
            "small": self.tier_small_provider,
            "mid": self.tier_mid_provider,
            "frontier": self.tier_frontier_provider,
            "deep_reasoning": self.tier_deep_reasoning_provider,
        }
        model_map: dict[str, str | None] = {
            "nano": self.tier_nano_model,
            "small": self.tier_small_model,
            "mid": self.tier_mid_model,
            "frontier": self.tier_frontier_model,
            "deep_reasoning": self.tier_deep_reasoning_model,
        }
        raw_provider = provider_map.get(tier)
        raw_model = model_map.get(tier)
        provider: LLMProviderName | None = None
        if isinstance(raw_provider, str) and raw_provider.strip():
            cleaned_provider = raw_provider.strip()
            if cleaned_provider in _SUPPORTED_PROVIDERS:
                provider = cast("LLMProviderName", cleaned_provider)
        model = raw_model.strip() if isinstance(raw_model, str) and raw_model.strip() else None
        return TierBinding(provider=provider, model=model)

    def resolve_tier_model(self, tier: str) -> str | None:
        """Map AgentConfig.model_tier → optional model id (compat helper)."""
        return self.resolve_tier_binding(tier).model


__all__ = [
    "AnthropicLLMConfig",
    "GatewayLLMConfig",
    "LLMConfig",
    "LLMProviderConfig",
    "LLMProviderName",
    "ModelTierName",
    "OllamaLLMConfig",
    "OpenAILLMConfig",
    "QwenLLMConfig",
    "TierBinding",
]
