"""Intent attachment axes + graph routing into the attachment stage (055, 065)."""

from __future__ import annotations

import json

from typing import Any
from uuid import uuid4

from langgraph.graph import END

from palatium_ai.application.agents.intent_classifier.parsing import parse_classifier_output
from palatium_ai.application.orchestration.nodes import (
    route_after_attachment_selection,
    route_after_intent,
)
from palatium_ai.core.types.graph_nodes import (
    NODE_ATTACHMENT_SELECTION,
    NODE_CONTEXT_ENRICHER_CONTINUATION,
    NODE_MEMORY_MUTATION,
)
from palatium_ai.domain.agents.intent import IntentClassifierOutput, IntentTaskResult
from palatium_ai.domain.attachments.context import AttachmentContextBlock, AttachmentTurnContext
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output


def _payload(**overrides: object) -> str:
    base: dict[str, object] = {
        "task_kind": "knowledge_request",
        "requires_mcp": False,
        "requires_user_choice": False,
        "underspecification_kind": "none",
        "candidate_capabilities": [],
        "grounding": "optional",
        "grounding_reason": "",
        "transformation": "none",
        "file_reference": "none",
        "response_shape": "auto",
        "attachment_scope": "auto",
        "attachment_kind": "any",
        "memory_mutation": "none",
        "memory_text": "",
        "memory_key": "",
        "confidence": 0.9,
        "reasoning": "test",
    }
    base.update(overrides)
    return json.dumps(base)


def _block(filename: str, *, mime_type: str = "application/pdf") -> AttachmentContextBlock:
    return AttachmentContextBlock(
        attachment_id=uuid4(),
        filename=filename,
        source=f"attachment:{filename}",
        fenced_text=wrap_untrusted_tool_output("Текст файла.", source=f"attachment:{filename}"),
        action="allow",
        mime_type=mime_type,
    )


def _classification(**overrides: object) -> IntentTaskResult:
    output = IntentClassifierOutput(
        task_kind="knowledge_request",
        requires_mcp=False,
        confidence=0.9,
        reasoning="test",
        **overrides,
    )
    return IntentTaskResult(
        task_id="task-1",
        agent_role="intent_classifier",
        status="success",
        confidence=0.9,
        output=output,
    )


def test_parse_attachment_axes() -> None:
    output = parse_classifier_output(_payload(attachment_scope="single", attachment_kind="image"))

    assert output.attachment_scope == "single"
    assert output.attachment_kind == "image"


def test_parse_unknown_attachment_axes_fall_back_without_a_card() -> None:
    output = parse_classifier_output(_payload(attachment_scope="???", attachment_kind="video"))

    assert output.attachment_scope == "auto"
    assert output.attachment_kind == "any"
    assert output.requires_user_choice is False


def test_multi_file_turn_routes_to_attachment_selection() -> None:
    state: dict[str, Any] = {
        "task_id": "task-1",
        "thread_id": "thread-1",
        "classification": _classification(),
        "attachment_context": AttachmentTurnContext(blocks=(_block("a.pdf"), _block("b.pdf"))),
    }

    assert route_after_intent(state) == NODE_ATTACHMENT_SELECTION


def test_one_file_turn_skips_the_attachment_stage() -> None:
    state: dict[str, Any] = {
        "task_id": "task-1",
        "thread_id": "thread-1",
        "classification": _classification(),
        "attachment_context": AttachmentTurnContext(blocks=(_block("a.pdf"),)),
    }

    assert route_after_intent(state) == NODE_CONTEXT_ENRICHER_CONTINUATION


def test_memory_mutation_wins_over_attachments() -> None:
    state: dict[str, Any] = {
        "task_id": "task-1",
        "thread_id": "thread-1",
        "classification": _classification(memory_mutation="save", memory_text="порт 5433"),
        "attachment_context": AttachmentTurnContext(blocks=(_block("a.pdf"), _block("b.pdf"))),
    }

    assert route_after_intent(state) == NODE_MEMORY_MUTATION


def test_pending_file_choice_ends_the_turn() -> None:
    assert route_after_attachment_selection({"formatted": object()}) == END  # type: ignore[typeddict-item]
    assert route_after_attachment_selection({}) == NODE_CONTEXT_ENRICHER_CONTINUATION  # type: ignore[typeddict-item]


def test_multi_file_turn_out_of_scope_does_not_ask_which_file() -> None:
    """Three attachments + «вопрос не про файлы» is not an ambiguity — no card (055)."""
    state: dict[str, Any] = {
        "task_id": "task-1",
        "thread_id": "thread-1",
        "user_text": "Вопрос не относится к файлам. Как меня зовут?",
        "classification": _classification(attachment_focus="none"),
        "attachment_context": AttachmentTurnContext(blocks=(_block("a.pdf"), _block("b.pdf"))),
    }

    assert route_after_intent(state) == NODE_CONTEXT_ENRICHER_CONTINUATION
