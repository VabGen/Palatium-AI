"""LLM JSON codec — brace-balanced extract + trailing-comma repair."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.formatter_agent import _parse_formatter_document
from palatium_ai.domain.llm.json_codec import extract_json_object, loads_llm_json


def test_loads_trailing_comma() -> None:
    raw = '{"a": 1, "b": [2, 3,],}'
    assert loads_llm_json(raw) == {"a": 1, "b": [2, 3]}


def test_extract_from_fenced_markdown() -> None:
    raw = 'Here:\n```json\n{"ok": true}\n```\n'
    assert loads_llm_json(raw) == {"ok": True}


def test_extract_balanced_not_greedy() -> None:
    raw = 'prefix {"inner": {"x": 1}} trailing }'
    assert extract_json_object(raw) == '{"inner": {"x": 1}}'


def test_formatter_parse_tolerates_trailing_commas() -> None:
    raw = """
    {
      "schema_version": 1,
      "locale": "ru-RU",
      "title": "Ответ",
      "blocks": [
        {"type": "paragraph", "text": "Ссылка на ст. 62 ХПК РБ.",},
      ],
      "actions": [],
      "meta": {"confidence": 0.9, "requires_review": false, "source_refs": [],},
    }
    """
    doc = _parse_formatter_document(raw)
    assert doc.locale == "ru-RU"
    assert "62" in doc.blocks[0].text  # type: ignore[attr-defined]


def test_loads_rejects_unbalanced() -> None:
    with pytest.raises(ValueError, match="Unbalanced|No JSON"):
        loads_llm_json('{"a": 1')


def test_strict_json_still_works() -> None:
    assert json.dumps(loads_llm_json('{"n": 1}')) == '{"n": 1}'
