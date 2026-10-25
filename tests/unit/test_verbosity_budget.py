"""W7: the answer's length budget is the server's decision, not the model's (050, 055).

``verbosity_budget`` is an axis, so it needs one owner. The user expresses it in words
("сократи", "подробнее"), and the only classified signal that survives is the
transformation axis — so the policy derives the budget from it and the pipeline stamps
the value into ``meta``. The model is told the budget, never asked to choose one: a field
the provider must fill becomes a guess, and a guessed axis measures nothing.
"""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.formatter.parsing import (
    align_formatter_meta,
    build_formatter_user_payload,
)
from palatium_ai.application.agents.formatter.prompts import FORMATTER_SCHEMA_PROMPT, FORMATTER_SYSTEM_PROMPT
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument, parse_content_document
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.policies.types import TRANSFORMATION_DEFAULT
from palatium_ai.domain.policies.verbosity import BUDGET_DEFAULT, VerbosityPolicy
from palatium_ai.infrastructure.llm.litellm_adapter import build_provider_response_format


def _formatter_input(*, transformation: str | None = TRANSFORMATION_DEFAULT) -> FormatterInput:
    packet = ContextPacket(
        task_id="t1",
        user_text="Сделай короче",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(strategy="reason_only", requires_tool_call=False, rationale="verbosity"),
        context_summary="verbosity",
    )
    return FormatterInput(
        task_id="t1",
        context_packet=packet,
        response_locale="ru-RU",
        transformation=transformation,  # type: ignore[arg-type]
    )


def _document(*, budget: str | None = None) -> ContentDocument:
    meta: dict[str, object] = {"confidence": 0.9, "kind": "response"}
    if budget is not None:
        meta["verbosity_budget"] = budget
    return parse_content_document({"locale": "ru-RU", "blocks": [{"type": "paragraph", "text": "Ответ."}], "meta": meta})


@pytest.mark.parametrize(
    "transformation,expected",
    (
        ("shorten", "minimal"),
        ("expand", "detailed"),
        ("rewrite", "standard"),
        ("restructure", "standard"),
        ("none", "standard"),
        ("", "standard"),
        ("made_up_value", "standard"),
        (None, "standard"),
    ),
)
def test_budget_follows_only_the_length_bearing_transformations(transformation: str | None, expected: str) -> None:
    assert VerbosityPolicy.for_transformation(transformation) == expected


def test_default_budget_is_standard_so_legacy_documents_stay_valid() -> None:
    """Additive field, no ``schema_version`` bump: a persisted document has no budget."""
    assert BUDGET_DEFAULT == "standard"
    assert _document().meta.verbosity_budget == "standard"


@pytest.mark.parametrize("budget", ("minimal", "standard", "detailed"))
def test_a_document_cannot_declare_its_own_budget(budget: str) -> None:
    """The model-emitted value never survives the pipeline boundary (single owner)."""
    for transformation, expected in (("shorten", "minimal"), ("expand", "detailed"), ("none", "standard")):
        aligned = align_formatter_meta(_document(budget=budget), _formatter_input(transformation=transformation))

        assert aligned.meta.verbosity_budget == expected


def test_budget_is_not_part_of_the_provider_schema() -> None:
    """A field in a strict output schema becomes required — the model would have to invent it."""
    payload = build_provider_response_format("json_schema", ContentDocument)

    assert payload is not None
    meta = payload["json_schema"]["schema"]["$defs"]["DocumentMeta"]
    assert "verbosity_budget" not in meta["properties"]
    assert "verbosity_budget" not in json.dumps(meta.get("required", []))


def test_payload_and_meta_read_the_same_policy() -> None:
    """The instruction the model gets and the value we persist cannot drift apart."""
    for transformation in ("shorten", "expand", "rewrite", "none"):
        task_input = _formatter_input(transformation=transformation)

        payload = build_formatter_user_payload(task_input)
        aligned = align_formatter_meta(_document(), task_input)

        assert payload["verbosity_budget"] == aligned.meta.verbosity_budget


@pytest.mark.parametrize("prompt", (FORMATTER_SYSTEM_PROMPT, FORMATTER_SCHEMA_PROMPT))
def test_both_generation_paths_are_told_about_the_budget(prompt: str) -> None:
    """The markdown fallback is what a provider failure lands on — it needs the axis too."""
    assert "verbosity_budget" in prompt
    for budget in ("minimal", "standard", "detailed"):
        assert f"- {budget}" in prompt


@pytest.mark.parametrize("prompt", (FORMATTER_SYSTEM_PROMPT, FORMATTER_SCHEMA_PROMPT))
def test_budget_never_licenses_dropping_a_limitation_or_citation(prompt: str) -> None:
    """Brevity is a length rule; faithfulness rules outrank it."""
    low = prompt.lower()
    assert "brevity never drops" in low
    assert "citation" in low
