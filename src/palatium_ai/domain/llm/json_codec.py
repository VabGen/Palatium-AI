"""Parse JSON objects from LLM text (fences, trailing commas, brace balance)."""

from __future__ import annotations

import json
import re

from typing import Any

_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
# Trailing commas before } or ] — common LLM JSON defect.
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def extract_json_object(raw: str) -> str:
    """Return the first balanced `{...}` substring (ignores greedy outer matches)."""
    text = raw.strip()
    fence = _FENCE.search(text)
    if fence is not None:
        text = fence.group(1).strip()

    start = text.find("{")
    if start < 0:
        raise ValueError(f"No JSON object found in LLM response: {text[:200]}")

    end = _find_matching_brace(text, start)
    if end < 0:
        raise ValueError(f"Unbalanced JSON object in LLM response: {text[:200]}")
    return text[start : end + 1]


def _find_matching_brace(text: str, start: int) -> int:
    """Index of closing `}` for the object that starts at ``start``, or -1."""
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        ch = text[index]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1


def loads_llm_json(raw: str) -> Any:
    """Parse an object/array from LLM output with light, deterministic repairs."""
    candidate = extract_json_object(raw)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        repaired = _TRAILING_COMMA.sub(r"\1", candidate)
        repaired = repaired.replace("\ufeff", "").replace("\u200b", "")
        return json.loads(repaired)
