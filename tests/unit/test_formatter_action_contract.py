"""The formatter prompt must document the closed enums it is validated against (010/055).

Regression (observed in the docker stack): the prompt told the model to emit
``{action_id,label,kind,style,icon}`` but never enumerated the allowed values, so it produced
``kind="action"``. That is not in ``ActionKind``, so the whole ContentDocument failed
validation and even the repair attempt failed the same way.
"""

from __future__ import annotations

from typing import get_args

import pytest

from pydantic import ValidationError

from palatium_ai.application.agents.formatter.prompts import FORMATTER_SYSTEM_PROMPT
from palatium_ai.domain.content import ActionKind, ActionSpec, ActionStyle


def test_prompt_lists_every_action_kind() -> None:
    for kind in get_args(ActionKind):
        assert f'"{kind}"' in FORMATTER_SYSTEM_PROMPT, f"prompt omits ActionKind {kind!r}"


def test_prompt_lists_every_action_style() -> None:
    for style in get_args(ActionStyle):
        assert f'"{style}"' in FORMATTER_SYSTEM_PROMPT, f"prompt omits ActionStyle {style!r}"


def test_prompt_kind_enum_matches_the_schema_exactly() -> None:
    """The prompt's enum must be the schema's enum — not a hand-maintained copy."""
    expected_kinds = "|".join(f'"{kind}"' for kind in get_args(ActionKind))
    expected_styles = "|".join(f'"{style}"' for style in get_args(ActionStyle))
    assert expected_kinds in FORMATTER_SYSTEM_PROMPT
    assert expected_styles in FORMATTER_SYSTEM_PROMPT


def test_prompt_announces_the_enums_are_closed() -> None:
    assert "CLOSED enum" in FORMATTER_SYSTEM_PROMPT


def test_documented_kind_validates_and_the_invented_one_does_not() -> None:
    """The value the model invented is rejected; the documented ones are accepted."""
    assert ActionSpec.model_validate({"action_id": "a", "label": "A", "kind": "approve"}).kind == "approve"
    with pytest.raises(ValidationError):
        ActionSpec.model_validate({"action_id": "a", "label": "A", "kind": "action"})
