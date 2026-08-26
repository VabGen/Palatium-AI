# src/palatium_ai/infrastructure/llm/litellm_model.py

"""Helpers for resolving LiteLLM model identifiers from provider config."""

from __future__ import annotations

_KNOWN_PREFIXES = frozenset(
    {
        "openai",
        "anthropic",
        "ollama",
        "ollama_chat",
        "huggingface",
        "azure",
        "bedrock",
        "vertex_ai",
        "cohere",
        "dashscope",
    }
)


def is_openai_compatible_base_url(base_url: str) -> bool:
    """Return True when the endpoint speaks OpenAI-compatible /v1 APIs."""
    normalized = base_url.rstrip("/").lower()
    return normalized.endswith("/v1") or "ollama.com" in normalized


def resolve_litellm_model(*, provider: str, model: str, base_url: str) -> str:
    """
    Prefix model names so LiteLLM can route the request.

    Bare names like ``gpt-oss:20b-cloud`` raise BadRequestError because LiteLLM
    cannot infer the provider. Ollama Cloud (``https://ollama.com/v1``) is an
    OpenAI-compatible API, so it must be routed as ``openai/<model>``.
    """
    if "/" in model:
        prefix = model.split("/", 1)[0]
        if prefix in _KNOWN_PREFIXES:
            return model

    if provider == "ollama":
        if is_openai_compatible_base_url(base_url):
            return f"openai/{model}"
        return f"ollama_chat/{model}"

    if provider == "openai":
        return f"openai/{model}"

    if provider == "anthropic":
        return f"anthropic/{model}"

    if provider == "qwen":
        # DashScope / corporate OpenAI-compatible gateways.
        if is_openai_compatible_base_url(base_url):
            return f"openai/{model}"
        return f"openai/{model}"

    return model
