"""Emptiness is a search-envelope contract, not "any JSON without hits" (055)."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.researcher.parsing import mcp_payload_is_empty


def test_empty_text_is_empty() -> None:
    assert mcp_payload_is_empty("   ") is True


def test_search_envelope_with_zero_hits_is_empty() -> None:
    raw = json.dumps({"tool": "search_knowledge", "hit_count": 0, "hits": []})

    assert mcp_payload_is_empty(raw) is True


def test_search_envelope_with_hits_is_not_empty() -> None:
    raw = json.dumps({"tool": "search_knowledge", "hit_count": 2, "hits": [{"text": "a"}, {"text": "b"}]})

    assert mcp_payload_is_empty(raw) is False


@pytest.mark.parametrize(
    "payload",
    (
        {"tool": "graph_query", "row_count": 1, "rows": [{"fact": "Palatium uses LangGraph"}]},
        {"tool": "read_attachment", "filename": "Договор.docx", "fenced_text": "Пункт 7.3"},
        {"tool": "web_fallback", "results": [{"title": "Doc", "url": "https://example.com"}]},
    ),
)
def test_foreign_tool_payloads_are_never_read_as_empty_search(payload: dict[str, object]) -> None:
    """The search model's ``hit_count=0`` default must not swallow other envelopes."""
    assert mcp_payload_is_empty(json.dumps(payload, ensure_ascii=False)) is False


def test_bool_hit_count_is_not_read_as_zero() -> None:
    assert mcp_payload_is_empty(json.dumps({"hit_count": True, "hits": []})) is False


def test_plain_text_body_is_not_empty() -> None:
    assert mcp_payload_is_empty("Полный текст документа без JSON.") is False
