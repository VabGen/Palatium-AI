"""Unit tests for LiteLLM model routing helpers."""

from __future__ import annotations

from palatium_ai.infrastructure.llm.litellm_model import (
    is_openai_compatible_base_url,
    resolve_litellm_model,
)


def test_ollama_cloud_uses_openai_compatible_prefix() -> None:
    """Ollama Cloud /v1 must be routed as openai/<model> for LiteLLM."""
    resolved = resolve_litellm_model(
        provider="ollama",
        model="gpt-oss:20b-cloud",
        base_url="https://ollama.com/v1",
    )
    assert resolved == "openai/gpt-oss:20b-cloud"


def test_local_ollama_uses_ollama_chat_prefix() -> None:
    """Native local Ollama should use ollama_chat/<model>."""
    resolved = resolve_litellm_model(
        provider="ollama",
        model="llama3.2",
        base_url="http://localhost:11434",
    )
    assert resolved == "ollama_chat/llama3.2"


def test_existing_prefix_is_preserved() -> None:
    """Already prefixed model names must not be double-prefixed."""
    resolved = resolve_litellm_model(
        provider="ollama",
        model="openai/gpt-oss:20b-cloud",
        base_url="https://ollama.com/v1",
    )
    assert resolved == "openai/gpt-oss:20b-cloud"


def test_corporate_embedding_gateway_is_openai_compatible() -> None:
    """Corporate /v1 embedding gateways should route as openai/<model>."""
    assert is_openai_compatible_base_url("http://model-embedding.shared.du.iba/v1")
    resolved = resolve_litellm_model(
        provider="qwen",
        model="embedding-model",
        base_url="http://model-embedding.shared.du.iba/v1",
    )
    assert resolved == "openai/embedding-model"
