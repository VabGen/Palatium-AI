# tests/unit/test_embedding_config.py

"""Тесты конфигурации embeddings-провайдеров."""

from __future__ import annotations

from pydantic import SecretStr

from palatium_ai.core.config.embeddings import CohereEmbeddingConfig, EmbeddingConfig


def test_embedding_config_supports_cohere_as_default_provider() -> None:
    config = EmbeddingConfig(
        default_provider="cohere",
        cohere=CohereEmbeddingConfig(api_key=SecretStr("test-key")),
    )

    active_provider = config.get_active_provider()

    assert active_provider.provider_name == "cohere"
    assert active_provider.get_api_key() == "test-key"
    assert active_provider.get_default_model() == "embed-multilingual-v3.0"
