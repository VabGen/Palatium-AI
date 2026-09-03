"""Unit-тесты ContentDocument и Formatter structured output."""

from __future__ import annotations

import json

import pytest

from pydantic import ValidationError

from palatium_ai.application.agents.formatter import parse_formatter_document
from palatium_ai.domain.content import (
    ContentDocument,
    HeadingBlock,
    ListBlock,
    StepsBlock,
    TableBlock,
    parse_content_document,
)


def _sample_payload(*, title: str = "Meeting plan", locale: str = "en-US") -> dict[str, object]:
    return {
        "schema_version": 1,
        "locale": locale,
        "title": title,
        "blocks": [
            {"type": "heading", "level": 2, "text": title, "icon": "calendar"},
            {
                "type": "paragraph",
                "text": "Follow these steps to schedule the meeting.",
            },
            {
                "type": "steps",
                "items": [
                    {
                        "title": "Collect details",
                        "body": "Time, agenda, participants.",
                        "status": "pending",
                        "icon": "edit",
                    },
                    {
                        "title": "Send invites",
                        "body": "Calendar invitations with confirmation.",
                        "status": "pending",
                        "icon": "mail",
                    },
                ],
            },
            {
                "type": "callout",
                "tone": "info",
                "title": "Note",
                "body": "Confirm timezone with all attendees.",
                "icon": "info",
            },
        ],
        "actions": [],
        "meta": {
            "confidence": 0.95,
            "requires_review": False,
            "source_refs": [],
        },
    }


def test_parse_content_document_happy_path() -> None:
    doc = parse_content_document(_sample_payload())
    assert doc.schema_version == 1
    assert doc.title == "Meeting plan"
    assert isinstance(doc.blocks[0], HeadingBlock)
    assert isinstance(doc.blocks[2], StepsBlock)
    assert doc.preview_text().startswith("Meeting plan")


def test_parse_rejects_unknown_block_type() -> None:
    payload = _sample_payload()
    blocks = list(payload["blocks"])  # type: ignore[arg-type]
    blocks.append({"type": "markdown", "text": "nope"})
    payload["blocks"] = blocks
    with pytest.raises(ValidationError):
        parse_content_document(payload)


def test_parse_rejects_bad_icon_token() -> None:
    payload = _sample_payload()
    blocks = list(payload["blocks"])  # type: ignore[arg-type]
    blocks[0] = {**blocks[0], "icon": "icons8-calendar"}  # type: ignore[index]
    payload["blocks"] = blocks
    with pytest.raises(ValidationError):
        parse_content_document(payload)


def test_table_row_width_validation() -> None:
    payload = _sample_payload()
    payload["blocks"] = [
        {
            "type": "table",
            "columns": ["A", "B"],
            "rows": [["1", "2", "3"]],
        }
    ]
    with pytest.raises(ValueError, match="table row"):
        parse_content_document(payload)


def test_chart_series_length_validation() -> None:
    payload = _sample_payload()
    payload["blocks"] = [
        {
            "type": "chart",
            "kind": "bar",
            "labels": ["Mon", "Tue"],
            "series": [{"name": "Load", "values": [1.0]}],
            "title": "Load",
        }
    ]
    with pytest.raises(ValueError, match="chart series"):
        parse_content_document(payload)


def test_formatter_parse_unwraps_document_key() -> None:
    wrapped = {"document": _sample_payload(title="Wrapped")}
    doc = parse_formatter_document(json.dumps(wrapped))
    assert doc.title == "Wrapped"
    assert len(doc.blocks) >= 1


def test_formatter_parse_list_block() -> None:
    payload = _sample_payload()
    payload["blocks"] = [
        {
            "type": "list",
            "style": "ordered",
            "items": [
                {"text": "One", "icon": "check", "emphasis": "First"},
                {"text": "Two", "icon": None, "emphasis": None},
            ],
        }
    ]
    doc = parse_content_document(payload)
    assert isinstance(doc.blocks[0], ListBlock)
    assert doc.blocks[0].style == "ordered"


def test_content_document_is_formatter_output_alias() -> None:
    from palatium_ai.domain.agents.formatter import FormatterOutput

    assert FormatterOutput is ContentDocument
    assert isinstance(parse_content_document(_sample_payload()), FormatterOutput)


def test_valid_table_ok() -> None:
    payload = _sample_payload()
    payload["blocks"] = [
        {
            "type": "table",
            "columns": ["Name", "Status"],
            "rows": [["Alice", "OK"], ["Bob", "Pending"]],
        }
    ]
    doc = parse_content_document(payload)
    assert isinstance(doc.blocks[0], TableBlock)
    assert len(doc.blocks[0].rows) == 2


@pytest.mark.asyncio
async def test_formatter_invalid_json_returns_stable_contract_code() -> None:
    """Broken LLM JSON → failure with FORMATTER_OUTPUT_INVALID, never a fake document."""
    from palatium_ai.domain.agents.context_packet import ContextPacket
    from palatium_ai.domain.agents.formatter import FORMATTER_OUTPUT_INVALID, FormatterInput
    from palatium_ai.domain.mcp.models import ToolExecutionPlan
    from tests.conftest import SequentialFakeLLMPort, run_formatter

    llm = SequentialFakeLLMPort(["not-json-at-all", "still-broken {"])
    packet = ContextPacket(
        task_id="t1",
        user_text="rewrite with citations",
        task_kind="response_formatting",
        route="formatter",
        route_plan="Format prior answer",
        requires_mcp=False,
        candidate_capabilities=("format",),
        execution_plan=ToolExecutionPlan(
            strategy="format_only",
            requires_tool_call=False,
            rationale="format continuation",
        ),
        context_summary="format_only",
    )
    result = await run_formatter(
        FormatterInput(
            task_id="t1",
            context_packet=packet,
            worker_summary="long legal text with quotes",
            critic_summary="",
            requires_review=False,
            revision_feedback=None,
        ),
        llm,
    )
    assert result.status == "failure"
    assert result.output is None
    assert result.error == FORMATTER_OUTPUT_INVALID
