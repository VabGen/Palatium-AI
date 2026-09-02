# tests/unit/test_embedding_config.py

"""Тесты конфигурации embeddings-провайдеров."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr

from palatium_ai.core.config.embeddings import CohereEmbeddingConfig, EmbeddingConfig

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
