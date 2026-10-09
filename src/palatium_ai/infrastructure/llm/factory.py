# src/palatium_ai/infrastructure/llm/factory.py

"""Фабрика LLM-адаптеров с явной инъекцией настроек и fallback-цепочкой."""

from __future__ import annotations

import time

from typing import TYPE_CHECKING

import structlog

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.resilience import CircuitOpenError, ConsecutiveFailureCircuit
from palatium_ai.domain.llm.errors import StructuredOutputUnsupportedError

from .litellm_adapter import LiteLLMAdapter

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from pydantic import BaseModel

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

_SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"openai", "anthropic", "ollama", "qwen", "gateway"})
# One log line per missing-key provider per process (wiring calls this per agent).
_SKIPPED_NO_KEY_LOGGED: set[str] = set()
# Fallbacks when Settings has no observability block (unit tests, ad-hoc factories).
_FALLBACK_FAILURES_TO_OPEN = 3
_FALLBACK_OPEN_SECONDS = 30.0
# Prometheus label for palatium_circuit_breaker_state (040: single label `target`).
_LLM_CIRCUIT_PREFIX = "llm:"


class LLMClientFactory:
    """Создаёт LLMPort для указанного провайдера.

    Owns the per-provider circuit breakers. State is keyed by provider name and lives
    on the factory, which the composition root creates once — so a provider that is
    failing fast for one agent is skipped fast for every other agent too.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._circuits: dict[str, ConsecutiveFailureCircuit] = {}

    def _circuit_for(self, provider: str) -> ConsecutiveFailureCircuit:
        """Shared breaker for one provider (thresholds from ObservabilityConfig)."""
        circuit = self._circuits.get(provider)
        if circuit is None:
            observability = getattr(self._settings, "observability", None)
            circuit = ConsecutiveFailureCircuit(
                failures_to_open=int(getattr(observability, "circuit_failures_to_open", _FALLBACK_FAILURES_TO_OPEN)),
                open_seconds=float(getattr(observability, "circuit_open_seconds", _FALLBACK_OPEN_SECONDS)),
            )
            self._circuits[provider] = circuit
        return circuit

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
        is_single_gateway = chain == ("gateway",)
        if env in {"staging", "production"} and len(chain) < 2 and not is_single_gateway:
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

        if env in {"staging", "production"} and len(adapters) < 2 and not is_single_gateway:
            msg = "LLM fallback chain must resolve to >=2 credentialed providers in staging/production"
            raise RuntimeError(msg)

        if len(adapters) == 1:
            port = adapters[0][1]
            return _AgentModelLLMAdapter(port, model) if model else port

        circuits = {provider: self._circuit_for(provider) for provider, _ in adapters}
        return _FallbackChainLLMAdapter(adapters, primary_model=model, circuits=circuits)


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
        response_model: type[BaseModel] | None = None,
    ) -> LLMCompletion:
        return await self._inner.generate(
            messages,
            model=model or self._model_override,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
        )

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        async for delta in self._inner.generate_stream(
            messages,
            model=model or self._model_override,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            response_model=response_model,
        ):
            yield delta


class _FallbackChainLLMAdapter:
    """Try providers in order; model override applies only to the primary entry.

    Per-provider circuit breakers make a dead provider cheap to skip: without them,
    every call pays the full provider timeout before failing over (see 020).
    """

    def __init__(
        self,
        adapters: list[tuple[str, LLMPort]],
        *,
        primary_model: str | None,
        circuits: dict[str, ConsecutiveFailureCircuit] | None = None,
    ) -> None:
        self._adapters = adapters
        self._primary_model = primary_model
        self._circuits: dict[str, ConsecutiveFailureCircuit] = dict(circuits or {})

    def _circuit(self, provider: str) -> ConsecutiveFailureCircuit:
        circuit = self._circuits.get(provider)
        if circuit is None:
            circuit = ConsecutiveFailureCircuit()
            self._circuits[provider] = circuit
        return circuit

    def _acquire(self, provider: str, errors: list[str], open_circuits: list[tuple[str, float]]) -> bool:
        """Claim permission to call ``provider``; record why when refused.

        ``is_open`` is a pure read (it may promote open → half_open); ``allow_request``
        is what consumes the single half-open probe, so it must run exactly once.
        """
        circuit = self._circuit(provider)
        now = time.monotonic()
        if circuit.is_open(now):
            agent_metrics.record_circuit_state(f"{_LLM_CIRCUIT_PREFIX}{provider}", circuit.state_code())
            retry_after = max(0.0, circuit.open_until - now)
            open_circuits.append((provider, retry_after))
            errors.append(f"{provider}: circuit open (retry after ~{retry_after:.0f}s)")
            return False
        if not circuit.allow_request(now):
            # Lost the half-open probe race against a concurrent call.
            errors.append(f"{provider}: half-open probe already in flight")
            return False
        return True

    def _record(self, provider: str, *, failed: bool) -> None:
        circuit = self._circuit(provider)
        if failed:
            circuit.record_failure(time.monotonic())
        else:
            circuit.record_success()
        agent_metrics.record_circuit_state(f"{_LLM_CIRCUIT_PREFIX}{provider}", circuit.state_code())

    def _capture_provider_failure(
        self,
        provider: str,
        exc: Exception,
        errors: list[str],
        unsupported: list[StructuredOutputUnsupportedError],
    ) -> None:
        """Record an outage. A json_schema refusal is a capability gap, not a dead provider."""
        if isinstance(exc, StructuredOutputUnsupportedError):
            unsupported.append(exc)
            errors.append(f"{provider}: structured output unsupported")
            logger.warning("llm.structured_output_unsupported", provider=provider)
            return
        self._record(provider, failed=True)
        errors.append(f"{provider}: {exc}")

    def _raise_exhausted(
        self,
        errors: list[str],
        open_circuits: list[tuple[str, float]],
        unsupported: list[StructuredOutputUnsupportedError] | None = None,
    ) -> None:
        """Fail fast when every provider is breaker-open; otherwise report real errors."""
        pending = unsupported or []
        if pending and len(pending) == len(errors) and not open_circuits:
            raise StructuredOutputUnsupportedError(
                "provider chain rejected json_schema structured output",
            ) from pending[-1]
        if open_circuits and len(open_circuits) == len(self._adapters):
            provider, retry_after = min(open_circuits, key=lambda item: item[1])
            raise CircuitOpenError(
                f"{_LLM_CIRCUIT_PREFIX}{provider}",
                retry_after_seconds=retry_after,
            )
        raise RuntimeError("All LLM providers in fallback chain failed: " + " | ".join(errors))

    async def generate(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> LLMCompletion:
        errors: list[str] = []
        open_circuits: list[tuple[str, float]] = []
        unsupported: list[StructuredOutputUnsupportedError] = []
        for index, (provider, port) in enumerate(self._adapters):
            if not self._acquire(provider, errors, open_circuits):
                continue
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
                    response_model=response_model,
                )
            except Exception as exc:
                self._capture_provider_failure(provider, exc, errors, unsupported)
                logger.warning(
                    "llm.fallback.try_next",
                    provider=provider,
                    attempt=index + 1,
                    error=str(exc),
                )
                continue
            self._record(provider, failed=False)
            if index > 0:
                agent_metrics.record_llm_fallback(to_provider=provider)
                logger.warning(
                    "llm.fallback.used",
                    provider=provider,
                    attempt=index + 1,
                    chain_size=len(self._adapters),
                )
            return completion
        self._raise_exhausted(errors, open_circuits, unsupported)
        raise AssertionError("unreachable: _raise_exhausted always raises")  # pragma: no cover

    async def generate_stream(
        self,
        messages: list[ChatMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: LLMResponseFormat | None = None,
        response_model: type[BaseModel] | None = None,
    ) -> AsyncIterator[LLMStreamDelta]:
        errors: list[str] = []
        open_circuits: list[tuple[str, float]] = []
        unsupported: list[StructuredOutputUnsupportedError] = []
        for index, (provider, port) in enumerate(self._adapters):
            if not self._acquire(provider, errors, open_circuits):
                continue
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
                    response_model=response_model,
                )
                async for delta in stream:
                    yield delta
            except Exception as exc:
                self._capture_provider_failure(provider, exc, errors, unsupported)
                logger.warning(
                    "llm.fallback.stream_try_next",
                    provider=provider,
                    attempt=index + 1,
                    error=str(exc),
                )
                continue
            self._record(provider, failed=False)
            if index > 0:
                agent_metrics.record_llm_fallback(to_provider=provider)
                logger.warning(
                    "llm.fallback.stream_used",
                    provider=provider,
                    attempt=index + 1,
                    chain_size=len(self._adapters),
                )
            return
        self._raise_exhausted(errors, open_circuits, unsupported)


def create_llm_client(settings: Settings, provider_name: str | None = None) -> LLMPort:
    """Создаёт LLM-адаптер для указанного провайдера."""
    return LLMClientFactory(settings).get_client(provider_name)
