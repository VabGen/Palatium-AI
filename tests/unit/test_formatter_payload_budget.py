"""Formatter LLM payload — minimal final_text path (065)."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.config import FORMATTER_ATTACHMENT_MAX_CHARS
from palatium_ai.application.agents.formatter.parsing import (
    build_formatter_user_message,
    build_formatter_user_payload,
)
from palatium_ai.domain.agents.context_packet import ContextPacket
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.mcp.models import ToolExecutionPlan
from palatium_ai.domain.memory.turns import DialogTurn, DialogTurnWindow


def _packet(**overrides: object) -> ContextPacket:
    base: dict[str, object] = {
        "task_id": "t1",
        "user_text": "summarize",
        "task_kind": "knowledge_request",
        "route": "researcher",
        "route_plan": "research then format",
        "requires_mcp": False,
        "candidate_capabilities": (),
        "execution_plan": ToolExecutionPlan(
            strategy="retrieve_then_reason",
            requires_tool_call=False,
            rationale="research",
        ),
        "context_summary": "A" * 2_000,
    }
    base.update(overrides)
    return ContextPacket(**base)  # type: ignore[arg-type]


def test_minimal_payload_with_source_omits_dialog_dumps_and_attachment() -> None:
    """Worker final_text is SoT — do not re-dump attachment fences (065 / latency)."""
    fence = (
        "<<<UNTRUSTED_TOOL_OUTPUT source=attachment:"
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:doc.docx>>>\n" + ("BODY " * 2_000) + "\n<<<END_UNTRUSTED_TOOL_OUTPUT>>>"
    )
    task = FormatterInput(
        task_id="t1",
        context_packet=_packet(untrusted_context=fence),
        worker_summary="Worker answer body.",
        critic_summary="C" * 2_000,
        requires_review=False,
        memory_hints=("меня зовут Гена",),
    )
    payload = build_formatter_user_payload(task)
    assert payload["final_text"] == "Worker answer body."
    assert payload["task_kind"] == "knowledge_request"
    # Single structure-free paragraph → shape-preserving hint (never icon sections).
    assert payload["style_hint"] == "plain_text"
    assert "dialog_history" not in payload
    assert "attachment_context" not in payload
    assert "critic_summary" not in payload
    assert "context_summary" not in payload
    assert "worker_summary" not in payload
    assert "меня зовут Гена" in str(payload["memory_hints"])


def test_no_source_keeps_dialog_and_clipped_attachment() -> None:
    turns = tuple(
        DialogTurn(
            thread_id="th1",
            role="user" if i % 2 == 0 else "assistant",
            content=("turn-" + str(i) + "-") * 200,
            seq=i,
        )
        for i in range(8)
    )
    fat = "X" * (FORMATTER_ATTACHMENT_MAX_CHARS + 500)
    fence = (
        "<<<UNTRUSTED_TOOL_OUTPUT source=attachment:"
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa:doc.docx>>>\n"
        f"{fat}\n<<<END_UNTRUSTED_TOOL_OUTPUT>>>"
    )
    task = FormatterInput(
        task_id="t1",
        context_packet=_packet(
            task_kind="social_conversation",
            route="formatter",
            untrusted_context=fence,
        ),
        worker_summary="",
        dialog_window=DialogTurnWindow(thread_id="th1", turns=turns),
    )
    payload = build_formatter_user_payload(task)
    # Social without worker: empty final_text (compose reply), stimulus in user_text.
    assert payload["final_text"] == ""
    assert payload["style_hint"] == "social_reply"
    assert "dialog_history" in payload
    assert payload["user_text"] == "summarize"
    assert "attachment_context" in payload
    assert len(str(payload["attachment_context"])) <= FORMATTER_ATTACHMENT_MAX_CHARS + 40
    dialog = str(payload["dialog_history"])
    assert len(dialog) <= 2_100


def test_social_greeting_does_not_echo_user_as_final_text() -> None:
    """Regression: social format_only must not present user_text as the answer body."""
    task = FormatterInput(
        task_id="t1",
        context_packet=_packet(
            user_text="привет",
            task_kind="social_conversation",
            route="formatter",
            route_plan="reply socially",
            execution_plan=ToolExecutionPlan(
                strategy="format_only",
                requires_tool_call=False,
                rationale="social",
            ),
            context_summary="social",
        ),
        worker_summary="",
    )
    payload = build_formatter_user_payload(task)
    assert payload["final_text"] == ""
    assert payload["user_text"] == "привет"
    assert payload["style_hint"] == "social_reply"
    assert payload["task_kind"] == "social_conversation"


def test_social_with_worker_draft_presents_worker() -> None:
    """If a draft already exists, social still formats that prose (no empty strip)."""
    task = FormatterInput(
        task_id="t1",
        context_packet=_packet(
            user_text="привет",
            task_kind="social_conversation",
            route="formatter",
        ),
        worker_summary="Здравствуйте! Чем могу помочь?",
    )
    payload = build_formatter_user_payload(task)
    assert payload["final_text"] == "Здравствуйте! Чем могу помочь?"
    assert payload["style_hint"] == "plain_text"
    assert "user_text" not in payload


def test_user_message_is_xml_wrapped() -> None:
    msg = build_formatter_user_message({"final_text": "hi", "style_hint": "brand_sections_icons"})
    assert msg.startswith("<formatter_input>")
    assert msg.endswith("</formatter_input>")
    assert '"final_text": "hi"' in msg
