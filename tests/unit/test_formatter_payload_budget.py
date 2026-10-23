"""Formatter LLM payload — minimal final_text path (065)."""

from __future__ import annotations

from palatium_ai.application.agents.formatter.config import FORMATTER_ATTACHMENT_MAX_CHARS
from palatium_ai.application.agents.formatter.parsing import (
    build_formatter_user_message,
    build_formatter_user_payload,
    formatter_attachment_stats,
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
    assert "attached_files" not in payload
    assert "critic_summary" not in payload
    assert "context_summary" not in payload
    assert "worker_summary" not in payload
    assert "меня зовут Гена" in str(payload["user_facts"])
    # LLM-facing payload must not teach the model our internal field names: the
    # model mirrors them into user prose and HITL card labels (055, 020).
    assert "attachment_context" not in payload
    assert "memory_hints" not in payload
    assert "prior_context" not in payload


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
    assert "attached_files" in payload
    assert len(str(payload["attached_files"])) <= FORMATTER_ATTACHMENT_MAX_CHARS + 40
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


def test_content_transform_uses_prior_answer_as_target_and_drops_hints() -> None:
    """Regression: «перепиши ответ короче» composed «Сравнение файлов».

    Without a worker draft the composer must transform the prior answer, not the ask,
    and remembered topics must not ride along (055, 060).
    """
    task = FormatterInput(
        task_id="t1",
        context_packet=_packet(
            user_text="перепиши ответ на обращение более короткое",
            task_kind="knowledge_request",
        ),
        worker_summary="",
        prior_context="Уважаемая Татьяна Васильевна! Ответ на ваше обращение рассмотрен.",
        transformation="shorten",
        memory_hints=("привет я геннадий а ты", "сравни файлы"),
        memory_hint_kinds=("fact", "fact"),
    )
    payload = build_formatter_user_payload(task)
    assert payload["transformation"] == "shorten"
    assert payload["final_text"].startswith("Уважаемая Татьяна Васильевна!")
    assert "user_facts" not in payload
    assert "Сравнение файлов" not in str(payload)


def test_user_message_is_xml_wrapped() -> None:
    msg = build_formatter_user_message({"final_text": "hi", "style_hint": "brand_sections_icons"})
    assert msg.startswith("<formatter_input>")
    assert msg.endswith("</formatter_input>")
    assert '"final_text": "hi"' in msg


def _fence(attachment_id: str, filename: str, body: str) -> str:
    return f"<<<UNTRUSTED_TOOL_OUTPUT source=attachment:{attachment_id}:{filename}>>>\n{body}\n<<<END_UNTRUSTED_TOOL_OUTPUT>>>"


def test_two_uploads_keep_both_fence_headers_under_budget() -> None:
    """Regression (055/065): the second upload must not vanish from the payload.

    Live symptom this reproduces: two scanned PDFs uploaded, format_only turn, and the
    answer said "only «Скан_2_Приложение.pdf» is available — upload the second file".
    Cause: head+tail clip on the joined fence dropped the second fence header while
    leaving an unlabeled text tail, so the model read one document.
    """
    fence_a = _fence("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "Скан_2_Приложение.pdf", "A" * 4_000)
    fence_b = _fence("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "Скан_1_Приложение.pdf", "B" * 4_000)
    joined = f"{fence_a}\n\n{fence_b}"
    assert len(joined) > FORMATTER_ATTACHMENT_MAX_CHARS

    task = FormatterInput(
        task_id="t1",
        context_packet=_packet(
            task_kind="response_formatting",
            route="formatter",
            route_plan="format the uploaded documents",
            untrusted_context=joined,
        ),
        worker_summary="",
    )
    payload = build_formatter_user_payload(task)
    delivered = str(payload["attached_files"])

    assert len(delivered) <= FORMATTER_ATTACHMENT_MAX_CHARS
    assert delivered.count("<<<UNTRUSTED_TOOL_OUTPUT") == 2
    assert delivered.count("<<<END_UNTRUSTED_TOOL_OUTPUT>>>") == 2
    assert "Скан_2_Приложение.pdf" in delivered
    assert "Скан_1_Приложение.pdf" in delivered
    # Body loss stays explicit — never a silent cut (020, 065).
    assert "truncated" in delivered

    stats = formatter_attachment_stats(task, payload)
    assert stats["attachment_fences"] == 2
    assert stats["attachment_fence_chars"] == len(joined)
    assert stats["attachment_payload_chars"] == len(delivered)
    assert stats["attachment_budget_trimmed"] is True


def test_attachment_stats_separate_by_design_omission_from_trim() -> None:
    """Worker draft is SoT → the fence is omitted on purpose, not trimmed (065)."""
    task = FormatterInput(
        task_id="t1",
        context_packet=_packet(
            untrusted_context=_fence("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "doc.docx", "B" * 4_000),
        ),
        worker_summary="Worker answer body.",
    )
    payload = build_formatter_user_payload(task)
    assert "attached_files" not in payload

    stats = formatter_attachment_stats(task, payload)
    assert stats["attachment_fences"] == 1
    assert stats["attachment_payload_chars"] == 0
    assert stats["attachment_budget_trimmed"] is False
