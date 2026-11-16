"""LLM JSON codec — brace-balanced extract + trailing-comma repair."""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.formatter import parse_formatter_document
from palatium_ai.domain.llm.json_codec import JSONCodec, LLMJSONError, loads_llm_json, loads_llm_object


def test_loads_trailing_comma() -> None:
    raw = '{"a": 1, "b": [2, 3,],}'
    assert loads_llm_json(raw) == {"a": 1, "b": [2, 3]}


def test_extract_from_fenced_markdown() -> None:
    raw = 'Here:\n```json\n{"ok": true}\n```\n'
    assert loads_llm_json(raw) == {"ok": True}


def test_extract_balanced_not_greedy() -> None:
    """Extraction must stop at the first balanced object, not swallow trailing text."""
    raw = 'prefix {"inner": {"x": 1}} trailing }'
    assert JSONCodec.extract(raw) == '{"inner": {"x": 1}}'
    assert loads_llm_object(raw) == {"inner": {"x": 1}}


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
    doc = parse_formatter_document(raw)
    assert doc.locale == "ru-RU"
    assert "62" in doc.blocks[0].text  # type: ignore[attr-defined]


def test_loads_rejects_unbalanced() -> None:
    with pytest.raises(ValueError, match=r"Unbalanced|No JSON"):
        loads_llm_json('{"a": 1')


def test_loads_reports_a_payload_free_reason() -> None:
    """Callers log the failure class, not the model's prose (020, 040)."""
    with pytest.raises(LLMJSONError) as unbalanced:
        loads_llm_json('{"a": 1')
    assert unbalanced.value.reason == "unbalanced"

    with pytest.raises(LLMJSONError) as empty:
        loads_llm_json("no payload here")
    assert empty.value.reason == "no_json"


def test_fence_does_not_cut_a_payload_that_contains_a_fence() -> None:
    """A ``` inside a code block's ``content`` is data, not the end of the payload."""
    payload = {
        "locale": "ru-RU",
        "blocks": [
            {"type": "paragraph", "text": "Пример ниже."},
            {"type": "code", "language": "markdown", "content": "```python\nprint(1)\n```"},
            {"type": "paragraph", "text": "Хвост после примера."},
        ],
        "meta": {"confidence": 0.9},
    }
    fenced = f"Вот документ:\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```\n"

    assert loads_llm_object(fenced) == payload


def test_extract_prefers_the_fenced_payload_over_earlier_prose_brackets() -> None:
    raw = 'См. [1] и {черновик}:\n```json\n{"blocks": []}\n```'
    assert loads_llm_object(raw) == {"blocks": []}


def test_truncated_fenced_payload_is_unbalanced_not_silently_empty() -> None:
    with pytest.raises(LLMJSONError) as error:
        loads_llm_json('```json\n{"blocks": [{"type": "paragraph"')
    assert error.value.reason == "unbalanced"


def test_strict_json_still_works() -> None:
    assert json.dumps(loads_llm_json('{"n": 1}')) == '{"n": 1}'
