"""Closed action enums live on the json_schema payload, not in prompt prose.

The old prompt listed ActionKind with a ``|``.join template and the model still
invented ``kind="action"``. json_schema strict mode is now the closed set.
"""

from __future__ import annotations

import json

from typing import get_args

import pytest

from pydantic import ValidationError

from palatium_ai.application.agents.formatter.prompts import FORMATTER_SYSTEM_PROMPT
from palatium_ai.domain.content import ActionKind, ActionSpec, ActionStyle, ContentDocument
from palatium_ai.infrastructure.llm.litellm_adapter import build_provider_response_format

#: The prompt this file used to guard against was an 11,625-char monolith. Each wave
#: that spends prompt space re-baselines the ceiling to today +5 % instead of "60 % of
#: the monolith": W6 few-shot moved the markdown path 6,961 → 7,511, W7 length budget
#: moved it to 7,890. The guard keeps its point — no return to the 11.6k prompt — and
#: stops silent creep from the next edit. Measured 2026-10-24.
_CEILING_CHARS = 8_300


def test_formatter_prompt_stays_below_the_documented_ceiling() -> None:
    """Few-shot examples are paid on every turn: growth past the ceiling is a decision."""
    assert len(FORMATTER_SYSTEM_PROMPT) <= _CEILING_CHARS


def test_formatter_prompt_keeps_transform_rule_for_shorten_rewrite() -> None:
    # Regression: "перепиши ответ короче" was answered as a file comparison because
    # the composer saw no explicit transform intent and pulled the thread topic (055).
    assert "transformation ∈ {expand, shorten, rewrite}" in FORMATTER_SYSTEM_PROMPT
    assert "compare files" in FORMATTER_SYSTEM_PROMPT


def test_formatter_prompt_keeps_behavior_and_drops_format_rules() -> None:
    # Security fence + the current GFM-era input marker and style hints stay; the legacy
    # JSON-prompt tokens (closed enums in prose, JSON-only output) must never come back.
    assert "<<<UNTRUSTED_TOOL_OUTPUT>>>" in FORMATTER_SYSTEM_PROMPT
    assert "<formatter_input>" in FORMATTER_SYSTEM_PROMPT
    assert "plain_text" in FORMATTER_SYSTEM_PROMPT
    assert "document_generation" in FORMATTER_SYSTEM_PROMPT
    assert "metrics_kv" not in FORMATTER_SYSTEM_PROMPT
    assert "choice_hitl" not in FORMATTER_SYSTEM_PROMPT
    assert "OUTPUT: ONLY one JSON" not in FORMATTER_SYSTEM_PROMPT
    assert "CLOSED enum" not in FORMATTER_SYSTEM_PROMPT


def test_json_schema_payload_lists_every_action_enum() -> None:
    payload = build_provider_response_format("json_schema", ContentDocument)
    assert payload is not None
    encoded = json.dumps(payload["json_schema"]["schema"])
    assert payload["json_schema"]["strict"] is True
    assert payload["json_schema"]["name"] == "ContentDocument"
    for kind in get_args(ActionKind):
        assert f'"{kind}"' in encoded
    for style in get_args(ActionStyle):
        assert f'"{style}"' in encoded


def test_documented_kind_validates_and_the_invented_one_does_not() -> None:
    """The value the model invented is rejected; the documented ones are accepted."""
    assert ActionSpec.model_validate({"action_id": "a", "label": "A", "kind": "approve"}).kind == "approve"
    with pytest.raises(ValidationError):
        ActionSpec.model_validate({"action_id": "a", "label": "A", "kind": "action"})
