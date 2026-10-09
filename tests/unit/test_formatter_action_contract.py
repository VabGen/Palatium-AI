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

_BASELINE_CHARS = 11_625


def test_formatter_prompt_shrunk_at_least_forty_percent() -> None:
    assert len(FORMATTER_SYSTEM_PROMPT) <= int(_BASELINE_CHARS * 0.6)


def test_formatter_prompt_keeps_behavior_and_drops_format_rules() -> None:
    assert "<<<UNTRUSTED_TOOL_OUTPUT>>>" in FORMATTER_SYSTEM_PROMPT
    assert "<input_contract>" in FORMATTER_SYSTEM_PROMPT
    assert "status_callout" in FORMATTER_SYSTEM_PROMPT
    assert "sections_unordered" in FORMATTER_SYSTEM_PROMPT
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
