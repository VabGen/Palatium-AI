# src/palatium_ai/core/config/llm/__init__.py

"""Модуль для настроек LLM."""

from __future__ import annotations

from typing import Literal, NamedTuple, cast

from pydantic import Field, model_validator

from palatium_ai.core.config.base import BaseConfig

from .anthropic import AnthropicLLMConfig
from .base import LLMProviderConfig
from .ollama import OllamaLLMConfig
from .openai import OpenAILLMConfig
from .qwen import QwenLLMConfig

LLMProviderName = Literal["openai", "anthropic", "ollama", "qwen"]
_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "ollama", "qwen"})
ModelTierName = Literal["nano", "small", "mid", "frontier", "deep_reasoning"]


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
    "LLMConfig",
    "LLMProviderName",
    "ModelTierName",
    "OpenAILLMConfig",
    "AnthropicLLMConfig",
    "OllamaLLMConfig",
    "QwenLLMConfig",
    "LLMProviderConfig",
    "TierBinding",
]
