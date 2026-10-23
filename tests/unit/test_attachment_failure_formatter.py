"""Level 3 anti-hallucination: attached-but-unreadable files get an honest answer.

Regression for the "Привет, я Palatium" greeting when OCR yielded nothing: the
trigger is typed state (``text_state="missing"``), not prompt wording (020, 055).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from palatium_ai.application.orchestration import nodes
from palatium_ai.domain.attachments.context import AttachmentContextBlock, AttachmentTurnContext
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output

_MISSING_NOTICE = "Файл приложен, но текст из него не извлечён."


def _missing_block(filename: str) -> AttachmentContextBlock:
    return AttachmentContextBlock(
        attachment_id=uuid4(),
        filename=filename,
        source=f"attachment:{filename}",
        fenced_text=wrap_untrusted_tool_output(_MISSING_NOTICE, source=f"attachment:{filename}"),
        action="allow",
        mime_type="image/webp",
        text_state="missing",
    )


def _formatter_input() -> MagicMock:
    stub = MagicMock()
    stub.task_id = "task-1"
    stub.response_locale = "ru-RU"
    stub.requires_review = False
    stub.requires_user_choice = False
    stub.underspecification_kind = "none"
    stub.context_packet.untrusted_context = ""
    return stub


def _state() -> dict[str, Any]:
    return {
        "task_id": "task-1",
        "thread_id": "thread-1",
        "user_text": "дай текст файла",
        "response_locale": "ru-RU",
        "attachment_context": AttachmentTurnContext(blocks=(_missing_block("broken.webp"),)),
    }


@pytest.mark.asyncio()
async def test_unreadable_attachment_answers_honestly_without_llm() -> None:
    harness = MagicMock()
    harness.execute_with_guardrails = AsyncMock()
    agent = MagicMock()
    agent.config.role = "formatter"

    with (
        patch.object(nodes, "OrchestrationSnapshot") as snapshot,
        patch(
            "palatium_ai.application.orchestration.node_inputs.build_formatter_input",
            return_value=_formatter_input(),
        ),
    ):
        snapshot.from_state.return_value = MagicMock()
        update = await nodes.formatter_node(_state(), agent, harness)

    result = update["formatted"]
    assert result is not None
    assert result.output is not None
    text = result.output.plain_text()
    assert "Не удалось извлечь текст" in text
    assert "Palatium" not in text
    assert "Привет" not in text
    harness.execute_with_guardrails.assert_not_called()


def test_text_state_drives_the_signal_not_prompt_text() -> None:
    """``all_text_missing`` is derived from blocks; one readable file clears it."""
    broken = _missing_block("broken.webp")
    readable = AttachmentContextBlock(
        attachment_id=uuid4(),
        filename="contract.pdf",
        source="attachment:contract.pdf",
        fenced_text=wrap_untrusted_tool_output("Условия договора.", source="attachment:contract.pdf"),
        action="allow",
        mime_type="application/pdf",
        text_state="extracted",
    )

    assert AttachmentTurnContext(blocks=(broken,)).all_text_missing is True
    assert AttachmentTurnContext(blocks=(broken, readable)).all_text_missing is False
