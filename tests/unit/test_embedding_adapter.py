"""Unit tests for LiteLLM embedding response parsing."""

from __future__ import annotations

import pytest

from httpx import Timeout

from palatium_ai.infrastructure.embeddings import litellm_adapter
from palatium_ai.infrastructure.embeddings.litellm_adapter import LiteLLMEmbeddingAdapter, _extract_embeddings


def test_extract_embeddings_from_dict_response() -> None:
    response = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    assert _extract_embeddings(response) == [[0.1, 0.2, 0.3]]


def test_extract_embeddings_from_model_dump() -> None:
    class Response:
        def model_dump(self) -> dict[str, object]:
            return {"data": [{"embedding": [4.0, 5.0]}]}

    assert _extract_embeddings(Response()) == [[4.0, 5.0]]


def test_extract_embeddings_from_object_like_items() -> None:
    class Item:
        embedding = [1.0, 2.0]

    class Response:
        data = [Item()]

    assert _extract_embeddings(Response()) == [[1.0, 2.0]]


@pytest.mark.asyncio()
async def test_embed_passes_configured_timeout_to_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    class Config:
        provider_name = "qwen"
        timeout = 17
        connect_timeout = 3

        def get_api_key(self) -> str | None:
            return None

        def get_base_url(self) -> str:
            return "https://embeddings.example/v1"

        def get_default_model(self) -> str:
            return "embedding-model"

        def get_dimension(self) -> int:
            return 3

    captured: dict[str, object] = {}

    async def fake_aembedding(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"data": [{"embedding": [0.1, 0.2, 0.3]}]}

    monkeypatch.setattr(litellm_adapter, "aembedding", fake_aembedding)
    monkeypatch.setattr(litellm_adapter, "shared_client_session", lambda: object())

    result = await LiteLLMEmbeddingAdapter(Config()).embed(["query"])

    assert result == [[0.1, 0.2, 0.3]]
    timeout = captured["timeout"]
    assert isinstance(timeout, Timeout)
    assert timeout.total == 17
    assert timeout.connect == 3
