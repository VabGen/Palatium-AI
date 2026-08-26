"""Unit tests for LiteLLM embedding response parsing."""

from __future__ import annotations

from palatium_ai.infrastructure.embeddings.litellm_adapter import _extract_embeddings


def test_extract_embeddings_from_dict_response() -> None:
    response = {"data": [{"embedding": [0.1, 0.2, 0.3]}]}
    assert _extract_embeddings(response) == [[0.1, 0.2, 0.3]]


def test_extract_embeddings_from_object_like_items() -> None:
    class Item:
        embedding = [1.0, 2.0]

    class Response:
        data = [Item()]

    assert _extract_embeddings(Response()) == [[1.0, 2.0]]
