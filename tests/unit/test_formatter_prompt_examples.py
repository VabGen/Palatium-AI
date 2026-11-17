"""W6: a few-shot example is a contract, not a sketch (030, 075, 050).

An example the provider is told to imitate must be *valid*: a JSON snippet that fails
``ContentDocument`` teaches the model an invalid schema at the exact moment the schema is
enforced, and an example the parser degrades teaches the fallback path the wrong shape.
Both paths are pinned here, plus the token price: a few-shot block is paid on every turn,
so growth has to be a decision, not an accident (W6: «замер до/после»).
"""

from __future__ import annotations

import json

import pytest

from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.application.agents.formatter.prompts import (
    FORMATTER_SCHEMA_PROMPT,
    FORMATTER_SYSTEM_PROMPT,
    MARKDOWN_SHAPE_EXAMPLES,
    SCHEMA_SHAPE_EXAMPLES,
)
from palatium_ai.core.context.tokens import count_tokens
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument, KeyValueBlock, StepsBlock, TableBlock
from palatium_ai.domain.mcp.models import ToolExecutionPlan

#: Prompt-size ceilings in ``count_tokens`` estimates (~4 chars/token): schema path
#: 1471 → 1771 (W6) → 1866 (W7) → ~2100 (kimi-answer-formatting document_analysis
#: few-shot, 2026-11-11); legacy similarly. Ceiling = measured + small buffer.
_SCHEMA_PROMPT_TOKEN_CEILING = 2500
_LEGACY_PROMPT_TOKEN_CEILING = 2600
#: Examples are illustrative, not the bulk of the instructions.
_EXAMPLES_SHARE_CEILING = 0.30

_SCHEMA_BY_LABEL = dict(SCHEMA_SHAPE_EXAMPLES)
_MARKDOWN_BY_LABEL = dict(MARKDOWN_SHAPE_EXAMPLES)


def _document(label: str) -> ContentDocument:
    return ContentDocument.model_validate(json.loads(_SCHEMA_BY_LABEL[label]))


def _formatter_input() -> FormatterInput:
    packet = ContextPacket(
        task_id="t1",
        user_text="Сравни два файла",
        task_kind="knowledge_request",
        route="researcher",
        route_plan="answer",
        requires_mcp=False,
        execution_plan=ToolExecutionPlan(strategy="reason_only", requires_tool_call=False, rationale="examples"),
        context_summary="examples",
    )
    return FormatterInput(task_id="t1", context_packet=packet, response_locale="ru-RU")


def _examples_block(prompt: str) -> str:
    """The ``## EXAMPLES`` section of a prompt, up to the next ``##`` heading."""
    start = prompt.index("## EXAMPLES")
    tail = prompt[start + len("## EXAMPLES") :]
    end = tail.find("\n## ")
    return tail if end < 0 else tail[:end]


@pytest.mark.parametrize("label", [label for label, _ in SCHEMA_SHAPE_EXAMPLES])
def test_schema_example_is_a_valid_document_with_blocks(label: str) -> None:
    """An example that does not validate would teach an invalid contract."""
    document = _document(label)

    assert document.blocks, "an empty example teaches the empty-document defect it must prevent"


@pytest.mark.parametrize("label", [label for label, _ in SCHEMA_SHAPE_EXAMPLES])
def test_schema_example_is_rendered_into_the_prompt(label: str) -> None:
    """A constant nobody pasted into the prompt is dead weight, not a few-shot."""
    assert f"### {label}" in FORMATTER_SCHEMA_PROMPT
    assert _SCHEMA_BY_LABEL[label] in FORMATTER_SCHEMA_PROMPT


def test_comparison_example_is_a_table_with_an_attribute_column() -> None:
    """The shape most often broken: a comparison delivered as bullets."""
    document = _document("comparison_table")

    assert [block.type for block in document.blocks] == ["table", "paragraph"]
    table = document.blocks[0]
    assert isinstance(table, TableBlock)
    assert len(table.columns) == 3  # attribute column + two compared items
    assert len(table.rows) >= 2
    assert document.meta.kind == "analysis"


def test_plan_example_is_steps_with_actionable_items() -> None:
    document = _document("plan")

    assert [block.type for block in document.blocks] == ["steps"]
    steps = document.blocks[0]
    assert isinstance(steps, StepsBlock)
    assert len(steps.items) >= 2
    assert document.meta.kind == "guide"


def test_prose_example_is_paragraphs_only() -> None:
    document = _document("prose")

    assert {block.type for block in document.blocks} == {"paragraph"}


def test_boundary_example_states_the_limitation_instead_of_inventing_facts() -> None:
    """A boundary example must show the honest dead end, not a plausible answer."""
    document = _document("boundary_no_source_text")

    assert {block.type for block in document.blocks} == {"paragraph"}
    assert document.meta.requires_review is True
    # Below the confidence gate: a limitation is not an answer the user can act on.
    assert document.meta.confidence < 0.7


@pytest.mark.parametrize(
    "label,expected",
    (
        ("comparison_table", ["table", "paragraph"]),
        ("plan", ["steps"]),
        ("prose", ["paragraph", "paragraph"]),
        (
            "document_analysis",
            ["heading", "kv", "heading", "list", "heading", "callout", "heading", "list"],
        ),
        ("boundary_no_source_text", ["paragraph"]),
    ),
)
def test_markdown_example_parses_to_the_shape_it_teaches(label: str, expected: list[str]) -> None:
    """The fallback path gets the same shapes — through the real parser, not by eye."""
    document = markdown_to_content_document(_MARKDOWN_BY_LABEL[label], _formatter_input())

    assert [block.type for block in document.blocks] == expected


def test_document_analysis_schema_example_is_dense() -> None:
    """Structure-dense, icon-sparse: lead + signal headings only (Big Tech laconic)."""
    document = _document("document_analysis")
    types = [block.type for block in document.blocks]
    assert types.count("heading") >= 2
    assert "kv" in types
    assert "list" in types
    assert "callout" in types
    headings = [block for block in document.blocks if block.type == "heading"]
    by_text = {block.text: getattr(block, "icon", None) for block in headings}
    assert by_text.get("Заказчик") == "search"
    assert by_text.get("Требования") is None
    assert by_text.get("Риски") == "warning"
    assert by_text.get("Рекомендации") == "check"
    lists = [block for block in document.blocks if block.type == "list"]
    assert all(item.icon is None for block in lists for item in block.items)


def test_prompts_pin_kv_label_value_orientation() -> None:
    """Structure maps must not teach content|part (screenshot: Суд…|Шапка)."""
    for prompt in (FORMATTER_SYSTEM_PROMPT, FORMATTER_SCHEMA_PROMPT):
        assert "Never invert" in prompt
        assert "part|content" in prompt or "Часть | Содержание" in prompt


def test_document_analysis_kv_example_keeps_short_labels() -> None:
    """Few-shot kv rows: label is the short key, value carries the content."""
    document = _document("document_analysis")
    kvs = [block for block in document.blocks if isinstance(block, KeyValueBlock)]
    assert kvs
    for block in kvs:
        for item in block.items:
            assert len(item.label) <= len(item.value) or len(item.label) <= 40


@pytest.mark.parametrize("label", [label for label, _ in MARKDOWN_SHAPE_EXAMPLES])
def test_markdown_example_is_rendered_into_the_prompt(label: str) -> None:
    assert f"### {label}" in FORMATTER_SYSTEM_PROMPT
    assert _MARKDOWN_BY_LABEL[label] in FORMATTER_SYSTEM_PROMPT


def test_prompt_size_stays_within_the_measured_budget() -> None:
    """Both paths pay the examples on every turn, so the price is pinned, not observed."""
    assert count_tokens(FORMATTER_SCHEMA_PROMPT) <= _SCHEMA_PROMPT_TOKEN_CEILING
    assert count_tokens(FORMATTER_SYSTEM_PROMPT) <= _LEGACY_PROMPT_TOKEN_CEILING


def test_examples_do_not_outgrow_the_instructions() -> None:
    """Examples are illustrative: when they dominate the prompt, rules stop being read."""
    for prompt in (FORMATTER_SCHEMA_PROMPT, FORMATTER_SYSTEM_PROMPT):
        share = count_tokens(_examples_block(prompt)) / count_tokens(prompt)
        assert share <= _EXAMPLES_SHARE_CEILING
