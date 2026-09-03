# tests/unit/test_embedding_config.py

"""Тесты конфигурации embeddings-провайдеров."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from palatium_ai.core.config.embeddings import (
    CohereEmbeddingConfig,
    EmbeddingConfig,
    OllamaEmbeddingConfig,
    OpenAIEmbeddingConfig,
    QwenEmbeddingConfig,
)
from palatium_ai.core.types.embeddings import KNOWLEDGE_EMBEDDING_DIM, MEMORY_EMBEDDING_DIM

if TYPE_CHECKING:
    import pytest


def test_embedding_config_supports_cohere_as_default_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Isolate from developer .env (COHERE_EMBEDDING_MODEL etc.).
    for key in (
        "COHERE_EMBEDDING_API_KEY",
        "COHERE_EMBEDDING_MODEL",
        "COHERE_EMBEDDING_BASE_URL",
        "EMBEDDING_DEFAULT_PROVIDER",
        "MEMORY_EMBEDDING_PROVIDER",
        "KNOWLEDGE_EMBEDDING_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)

    config = EmbeddingConfig(
        default_provider="cohere",
        cohere=CohereEmbeddingConfig(
            api_key=SecretStr("test-key"),
            default_model="embed-multilingual-v3.0",
        ),
    )

    active_provider = config.get_active_provider()

    assert active_provider.provider_name == "cohere"
    assert active_provider.get_api_key() == "test-key"
    assert active_provider.get_default_model() == "embed-multilingual-v3.0"


def test_resolve_provider_for_schema_prefers_matching_dim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "EMBEDDING_DEFAULT_PROVIDER",
        "MEMORY_EMBEDDING_PROVIDER",
        "KNOWLEDGE_EMBEDDING_PROVIDER",
        "OPENAI_EMBEDDING_API_KEY",
        "QWEN_EMBEDDING_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    config = EmbeddingConfig(
        default_provider="openai",
        qwen=QwenEmbeddingConfig(
            api_key=SecretStr("qwen-key"),
            dimension=MEMORY_EMBEDDING_DIM,
        ),
        openai=OpenAIEmbeddingConfig(
            api_key=SecretStr("openai-key"),
            dimension=KNOWLEDGE_EMBEDDING_DIM,
        ),
        ollama=OllamaEmbeddingConfig(dimension=768),
        memory_provider="qwen",
        knowledge_provider="openai",
    )

    assert config.resolve_provider_name_for_schema("memory") == "qwen"
    assert config.resolve_provider_name_for_schema("knowledge") == "openai"
    assert config.expected_dim_for_schema("memory") == MEMORY_EMBEDDING_DIM
    assert config.expected_dim_for_schema("knowledge") == KNOWLEDGE_EMBEDDING_DIM


def test_resolve_provider_for_schema_returns_none_when_dim_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for key in (
        "EMBEDDING_DEFAULT_PROVIDER",
        "MEMORY_EMBEDDING_PROVIDER",
        "KNOWLEDGE_EMBEDDING_PROVIDER",
        "QWEN_EMBEDDING_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    config = EmbeddingConfig(
        default_provider="ollama",
        qwen=QwenEmbeddingConfig(
            api_key=SecretStr("qwen-key"),
            dimension=768,
        ),
        # ollama=768 / openai without key / qwen 768 → no 4096 or 1536 match.
        ollama=OllamaEmbeddingConfig(dimension=768),
        openai=OpenAIEmbeddingConfig(api_key=None, dimension=1536),
    )

    assert config.resolve_provider_name_for_schema("memory") is None
    assert config.resolve_provider_name_for_schema("knowledge") is None
