# src/palatium_ai/infrastructure/llm/factory.py

"""Фабрика LLM-адаптеров с явной инъекцией настроек и fallback-цепочкой."""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

from .litellm_adapter import LiteLLMAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from palatium_ai.core.config.llm.base import LLMProviderConfig
    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.agents.agent_config import AgentConfig
    from palatium_ai.domain.llm.models import (
        ChatMessage,
        LLMCompletion,
        LLMResponseFormat,
        LLMStreamDelta,
    )
    from palatium_ai.domain.ports.llm import LLMPort

logger = structlog.get_logger(__name__)

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "ollama", "qwen"})
# One log line per missing-key provider per process (wiring calls this per agent).
_SKIPPED_NO_KEY_LOGGED: set[str] = set()


class LLMClientFactory:
    """Создаёт LLMPort для указанного провайдера."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def get_client(self, provider_name: str | None = None) -> LLMPort:
        """Возвращает адаптер для провайдера (или default из настроек)."""
        resolved = provider_name or self._settings.llm.default_provider
        if resolved not in _SUPPORTED_PROVIDERS:
            raise ValueError(f"Unknown provider: {resolved}")

        config: LLMProviderConfig = getattr(self._settings.llm, resolved)
        return LiteLLMAdapter(config)

    @staticmethod
    def _provider_has_credentials(settings_llm: object, provider_name: str) -> bool:
        """Skip key-gated fallbacks when the API key is empty (avoids noisy failovers)."""
        config = getattr(settings_llm, provider_name, None)
        if config is None:
            return True
        get_key = getattr(config, "get_api_key", None)
        if not callable(get_key):
            return True
        key = get_key()
        if provider_name in {"openai", "anthropic", "qwen"}:
            return bool(key and str(key).strip())
        return True

    def get_client_for_agent(self, agent_config: AgentConfig) -> LLMPort:
        """Resolve client: agent override → tier → default, then wrap fallback chain."""
        tier = self._settings.llm.resolve_tier_binding(agent_config.model_tier)
        primary = agent_config.llm_provider or tier.provider or self._settings.llm.default_provider
        model = agent_config.llm_model or tier.model
        chain = self._settings.llm.build_provider_chain(primary)
        env = self._settings.app.environment
        if env in {"staging", "production"} and len(chain) < 2:
            msg = "LLM fallback chain must include >=2 providers in staging/production"
            raise RuntimeError(msg)
        if len(chain) < 2:
            logger.debug(
                "llm.fallback.chain_short",
                primary=primary,
                hint="Set LLM_FALLBACK_PROVIDERS to enable 2+ provider failover",
            )

        adapters: list[tuple[str, LLMPort]] = []
        for provider in chain:
            if not self._provider_has_credentials(self._settings.llm, provider):
                if provider not in _SKIPPED_NO_KEY_LOGGED:
                    _SKIPPED_NO_KEY_LOGGED.add(provider)
                    logger.warning(
                        "llm.fallback.provider_skipped_no_key",
                        provider=provider,
                        hint=(f"Set {provider.upper()}_API_KEY or remove {provider!r} from LLM_FALLBACK_PROVIDERS"),
                    )
                continue
            try:
                adapters.append((provider, self.get_client(provider)))
            except Exception as exc:
                logger.warning(
                    "llm.fallback.provider_unavailable",
                    provider=provider,
                    error=str(exc),
                )

        if not adapters:
            raise ValueError(f"No usable LLM providers in chain starting with {primary!r}")

        if env in {"staging", "production"} and len(adapters) < 2:
            msg = "LLM fallback chain must resolve to >=2 credentialed providers in staging/production"
            raise RuntimeError(msg)

        if len(adapters) == 1:
            port = adapters[0][1]
            return _AgentModelLLMAdapter(port, model) if model else port

        return _FallbackChainLLMAdapter(adapters, primary_model=model)


class _AgentModelLLMAdapter:
    """Обёртка: подставляет model override из AgentConfig / tier map."""

    def __init__(self, inner: LLMPort, model_override: str) -> None:
        self._inner = inner
        self._model_override = model_override

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        return await self._inner.generate(
            messages,
            model=model or self._model_override,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        async for delta in self._inner.generate_stream(
            messages,
            model=model or self._model_override,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        ):
            yield delta


class _FallbackChainLLMAdapter:
    """Try providers in order; model override applies only to the primary entry."""

    def __init__(
        self,
        adapters: list[tuple[str, LLMPort]],
        *,
        primary_model: str | None,
    ) -> None:
        self._adapters = adapters
        self._primary_model = primary_model

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> LLMCompletion:
        errors: list[str] = []
        for index, (provider, port) in enumerate(self._adapters):
            model_arg = model
            if model_arg is None and index == 0:
                model_arg = self._primary_model
            try:
                completion = await port.generate(
                    messages,
                    model=model_arg,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
                if index > 0:
                    logger.warning(
                        "llm.fallback.used",
                        provider=provider,
                        attempt=index + 1,
                        chain_size=len(self._adapters),
                    )
                return completion
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                logger.warning(
                    "llm.fallback.try_next",
                    provider=provider,
                    attempt=index + 1,
                    error=str(exc),
                )
        raise RuntimeError("All LLM providers in fallback chain failed: " + " | ".join(errors))

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        errors: list[str] = []
        for index, (provider, port) in enumerate(self._adapters):
            model_arg = model
            if model_arg is None and index == 0:
                model_arg = self._primary_model
            try:
                stream = port.generate_stream(
                    messages,
                    model=model_arg,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                )
                async for delta in stream:
                    yield delta
                return
            except Exception as exc:
                errors.append(f"{provider}: {exc}")
                logger.warning(
                    "llm.fallback.stream_try_next",
                    provider=provider,
                    attempt=index + 1,
                    error=str(exc),
                )
        raise RuntimeError("All LLM providers in fallback chain failed (stream): " + " | ".join(errors))


def create_llm_client(settings: Settings, provider_name: str | None = None) -> LLMPort:
    """Создаёт LLM-адаптер для указанного провайдера."""
    return LLMClientFactory(settings).get_client(provider_name)
