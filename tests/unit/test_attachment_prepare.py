"""AttachmentPrepareService: selection card + Map-Reduce budgeting (Level 1/2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest

from palatium_ai.application.services.attachment_prepare import AttachmentPrepareService
from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.hitl.cards import HITLCardView, HITLOption
from palatium_ai.domain.hitl.file_choice import ALL_FILES_ACTION_ID
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output

_LONG_BODY = "Условия договора и приложения к нему. " * 60


def _block(
    filename: str,
    *,
    mime_type: str = "application/pdf",
    text_state: str = "extracted",
    body: str = "Условия договора: срок 12 месяцев.",
) -> AttachmentContextBlock:
    return AttachmentContextBlock(
        attachment_id=uuid4(),
        filename=filename,
        source=f"attachment:{filename}",
        fenced_text=wrap_untrusted_tool_output(body, source=f"attachment:{filename}"),
        action="allow",
        mime_type=mime_type,
        text_state=text_state,  # type: ignore[arg-type]  # both closed states are exercised
    )


class _RecordingSummarizer:
    def __init__(self, *, summary: str = "Краткая выжимка файла.", fail_on: str | None = None) -> None:
        self.calls: list[str] = []
        self._summary = summary
        self._fail_on = fail_on

    async def __call__(self, body: str, filename: str) -> str:
        self.calls.append(filename)
        if filename == self._fail_on:
            raise RuntimeError("map stage boom")
        return f"{self._summary} ({len(body)} chars)"


class _CardService:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create_choice_card(self, **kwargs: Any) -> HITLCardView:
        self.calls.append(kwargs)
        now = datetime(2026, 1, 1, tzinfo=UTC)
        actions = kwargs["actions"]
        return HITLCardView(
            card_id="card-files",
            thread_id=kwargs["thread_id"],
            task_id=kwargs["task_id"],
            purpose="user_choice",
            title=kwargs["title"],
            options=tuple(
                HITLOption(action_id=a.action_id, label=a.label, kind=a.kind, action_token="tok")
                for a in actions
            ),
            risk_score=0.1,
            created_at=now,
            expires_at=now,
        )


async def _prepare(
    service: AttachmentPrepareService,
    blocks: Sequence[AttachmentContextBlock],
    *,
    scope: str = "auto",
    kind: str = "any",
    ask: str = "дай текст файла",
):
    return await service.prepare(
        blocks=blocks,
        task_id="task-1",
        thread_id="thread-1",
        user_id="user-1",
        org_id=None,
        locale="ru-RU",
        ask=ask,
        scope=scope,  # type: ignore[arg-type]  # closed Literal exercised per test
        kind=kind,  # type: ignore[arg-type]
    )


@pytest.mark.asyncio()
async def test_no_blocks_is_unchanged() -> None:
    outcome = await _prepare(AttachmentPrepareService(), ())

    assert outcome.status == "unchanged"
    assert outcome.blocks == ()


@pytest.mark.asyncio()
async def test_unambiguous_turn_is_prepared_with_original_fences() -> None:
    blocks = (_block("a.pdf"), _block("b.pdf"))
    service = AttachmentPrepareService(summarizer=_RecordingSummarizer())

    outcome = await _prepare(service, blocks, ask="сделай план по документам")

    assert outcome.status == "prepared"
    assert outcome.reduced is False
    assert outcome.blocks == blocks
    assert outcome.fenced_text == "\n\n".join(block.fenced_text for block in blocks)


@pytest.mark.asyncio()
async def test_ambiguity_mints_file_card_and_stops_the_turn() -> None:
    cards = _CardService()
    service = AttachmentPrepareService(hitl_service=cards, summarizer=_RecordingSummarizer())
    blocks = (_block("a.pdf"), _block("b.pdf"), _block("scan.webp", mime_type="image/webp"))

    outcome = await _prepare(service, blocks, scope="single", ask="сделай реферирование файла")

    assert outcome.status == "needs_choice"
    assert outcome.result is not None
    assert outcome.result.status == "partial"
    assert outcome.result.requires_review is True
    assert len(outcome.result.hitl_cards) == 1
    option_ids = [option.action_id for option in outcome.result.hitl_cards[0].options]
    assert option_ids == ["filesel_1", "filesel_2", "filesel_3", ALL_FILES_ACTION_ID]
    assert len(cards.calls) == 1
    assert cards.calls[0]["thread_id"] == "thread-1"


@pytest.mark.asyncio()
async def test_ambiguity_without_card_store_is_an_honest_failure() -> None:
    service = AttachmentPrepareService(summarizer=_RecordingSummarizer())
    blocks = (_block("a.pdf"), _block("b.pdf"))

    outcome = await _prepare(service, blocks, scope="single")

    assert outcome.status == "needs_choice"
    assert outcome.result is not None
    assert outcome.result.status == "failure"
    assert outcome.result.error == "attachment_selection_unavailable"
    assert outcome.result.hitl_cards == ()


@pytest.mark.asyncio()
async def test_single_file_is_never_summarized() -> None:
    summarizer = _RecordingSummarizer()
    service = AttachmentPrepareService(summarizer=summarizer)

    outcome = await _prepare(service, (_block("big.pdf", body=_LONG_BODY * 20),))

    assert outcome.status == "prepared"
    assert outcome.reduced is False
    assert summarizer.calls == []


@pytest.mark.asyncio()
async def test_token_overflow_triggers_parallel_map_reduce() -> None:
    summarizer = _RecordingSummarizer()
    service = AttachmentPrepareService(
        summarizer=summarizer,
        map_reduce_threshold_tokens=256,
        map_reduce_block_chars=400,
    )
    blocks = (
        _block("a.pdf", body=_LONG_BODY),
        _block("b.pdf", body=_LONG_BODY),
    )

    outcome = await _prepare(service, blocks, ask="сделай выжимку по всем файлам")

    assert outcome.status == "prepared"
    assert outcome.reduced is True
    assert sorted(summarizer.calls) == ["a.pdf", "b.pdf"]
    # Summaries stay fenced: the citation/injection contract survives the Reduce stage.
    assert "<<<UNTRUSTED_TOOL_OUTPUT" in outcome.fenced_text
    assert "Краткая выжимка файла." in outcome.fenced_text
    assert _LONG_BODY.strip() not in outcome.fenced_text


@pytest.mark.asyncio()
async def test_failed_map_keeps_a_clipped_fence_instead_of_dropping_the_file() -> None:
    service = AttachmentPrepareService(
        summarizer=_RecordingSummarizer(fail_on="b.pdf"),
        map_reduce_threshold_tokens=256,
        map_reduce_block_chars=400,
    )
    blocks = (
        _block("a.pdf", body=_LONG_BODY),
        _block("b.pdf", body=_LONG_BODY),
    )

    outcome = await _prepare(service, blocks, ask="сделай выжимку по всем файлам")

    assert outcome.status == "prepared"
    assert outcome.reduced is True
    assert "Map stage failed" in outcome.fenced_text
    assert "attachment:b.pdf" in outcome.fenced_text
    assert "attachment:a.pdf" in outcome.fenced_text


@pytest.mark.asyncio()
async def test_missing_text_file_is_summarized_as_unavailable_not_hallucinated() -> None:
    summarizer = _RecordingSummarizer()
    service = AttachmentPrepareService(
        summarizer=summarizer,
        map_reduce_threshold_tokens=256,
    )
    blocks = (
        _block("a.pdf", body=_LONG_BODY),
        _block("broken.webp", mime_type="image/webp", text_state="missing", body="Текст не извлечён."),
    )

    outcome = await _prepare(service, blocks, ask="сделай выжимку по всем файлам")

    assert outcome.reduced is True
    assert summarizer.calls == ["a.pdf"]
    assert "текст из него не извлечён" in outcome.fenced_text
    assert "не выдумывай его" in outcome.fenced_text
