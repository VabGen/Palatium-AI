"""Intent Guard: the turn's fenced uploads are withheld when the ask disowns them (055).

Covers the two "context bleed" cases from the golden matrix:
* a chitchat/memory question sent with an upload must not carry the document text;
* an explicit «не про файлы» label detaches it even on a knowledge ask.
The decision is taken from typed axes only — no phrase list, no prompt hope.
"""

from __future__ import annotations

from typing import cast

import pytest

from palatium_ai.application.agents.intent_classifier.parsing import parse_classifier_output
from palatium_ai.application.orchestration import selectors
from palatium_ai.application.orchestration.state import AgentGraphState
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.policies import EffectiveRoutingIntent
from palatium_ai.domain.policies.attachment_focus import AttachmentPromptPolicy

_FENCE = (
    '<untrusted_content source="attachment:contract.txt">\nДоговор поставки №42. Сроки поставки: 30 дней.\n</untrusted_content>'
)


def _classification(*, task_kind: str, focus: str) -> IntentTaskResult:
    return IntentTaskResult(
        task_id="task-guard",
        agent_role="intent_classifier",
        status="success",
        confidence=0.9,
        output=IntentClassifierOutput(
            task_kind=task_kind,  # type: ignore[arg-type]  # closed Literal under test
            requires_mcp=False,
            attachment_focus=focus,  # type: ignore[arg-type]  # closed Literal under test
            confidence=0.9,
            reasoning="axis under test",
        ),
    )


def _state(*, task_kind: str, focus: str) -> AgentGraphState:
    return cast(
        "AgentGraphState",
        {
            "task_id": "task-guard",
            "thread_id": "thread-guard",
            "user_text": "Вопрос не относится к файлам. Как меня зовут?",
            "untrusted_context": _FENCE,
            "classification": _classification(task_kind=task_kind, focus=focus),
            "routing_intent": EffectiveRoutingIntent(
                task_kind=task_kind,  # type: ignore[arg-type]  # closed Literal under test
                reasoning="axis under test",
            ),
        },
    )


def _packet(state: AgentGraphState) -> str:
    packet = selectors.resolved_context_packet(
        state,
        fallback_strategy="reason_only",
        fallback_rationale="guard test",
    )
    return packet.untrusted_context


@pytest.mark.parametrize(
    "task_kind, focus, expected",
    (
        ("knowledge_request", "current_uploads", True),
        ("knowledge_request", "none", False),
        ("social_conversation", "current_uploads", False),
        ("clarification_needed", "current_uploads", False),
        ("tool_execution", "current_uploads", True),
    ),
)
def test_policy_matrix(task_kind: str, focus: str, expected: bool) -> None:
    assert (
        AttachmentPromptPolicy.includes_uploads(
            task_kind=task_kind,  # type: ignore[arg-type]  # closed Literal under test
            focus=focus,  # type: ignore[arg-type]  # closed Literal under test
        )
        is expected
    )


def test_stubborn_user_turn_does_not_carry_the_document() -> None:
    """«Вопрос не про файлы. Как меня зовут?» → no fence in any prompt."""
    state = _state(task_kind="knowledge_request", focus="none")
    assert selectors.uploads_in_scope(state) is False
    assert _packet(state) == ""


def test_social_turn_with_upload_does_not_carry_the_document() -> None:
    state = _state(task_kind="social_conversation", focus="current_uploads")
    assert _packet(state) == ""


def test_file_ask_keeps_the_fence() -> None:
    state = _state(task_kind="knowledge_request", focus="current_uploads")
    assert selectors.uploads_in_scope(state) is True
    assert "Договор поставки №42" in _packet(state)


def test_detach_reason_is_observable() -> None:
    assert AttachmentPromptPolicy.detach_reason(task_kind="social_conversation", focus="none") == (
        "task_kind=social_conversation"
    )
    assert AttachmentPromptPolicy.detach_reason(task_kind="knowledge_request", focus="none") == ("attachment_focus=none")
    assert AttachmentPromptPolicy.detach_reason(task_kind="knowledge_request", focus="current_uploads") == "attached"


def test_unknown_focus_label_keeps_the_uploads() -> None:
    """A malformed label must not silently drop evidence (fail-safe default)."""
    parsed = parse_classifier_output(
        '{"task_kind": "knowledge_request", "requires_mcp": false, "attachment_focus": "bogus", '
        '"confidence": 0.9, "reasoning": "x"}',
    )
    assert parsed.attachment_focus == "current_uploads"


def test_explicit_none_focus_is_parsed() -> None:
    parsed = parse_classifier_output(
        '{"task_kind": "knowledge_request", "requires_mcp": false, "attachment_focus": "none", '
        '"confidence": 0.9, "reasoning": "user set the files aside"}',
    )
    assert parsed.attachment_focus == "none"


def test_scope_and_kind_reach_the_model_input() -> None:
    """The classifier must see the real plurality/modality, not guess it from prose."""
    from uuid import uuid4

    from palatium_ai.application.orchestration.agent_bridge import intent_to_agent_input
    from palatium_ai.domain.agents.intent import IntentClassifierInput

    agent_input = intent_to_agent_input(
        IntentClassifierInput(
            task_id="task-1",
            text="дай текст файла",
            attachment_count=3,
            attachment_kinds=("image", "document"),
        ),
        trace_id="trace-1",
        thread_id=str(uuid4()),
    )
    assert agent_input.context["attachment_count"] == "3"
    assert agent_input.context["attachment_kinds"] == "image,document"
