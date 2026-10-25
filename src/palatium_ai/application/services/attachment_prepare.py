"""Turn attachment preparation: deterministic selection + Map-Reduce budgeting.

Runs once per turn, after Intent and before any worker or Formatter LLM (065).
Two responsibilities that own the same artifact — the turn's fenced attachment
context:

* **Select** (Level 1): which current-turn files the ask targets. The choice is
  made by ``AttachmentSelectionPolicy`` (pure, no LLM). Several eligible files
  under a singular ask produce a **file-choice card** and stop the turn before a
  worker can guess (020, 055).
* **Budget** (Level 2): when the selected fences exceed the prompt token
  threshold, each file is summarized in parallel (Map) and the reduced fences
  are handed to the Reduce stage — the worker (the blueprint's Map-Reduce).
  A per-file failure degrades to an explicit clipped fence, never to a dropped
  file or a crashed turn (030.8, 065).

Text never leaves this module unfenced: summaries are re-wrapped with the same
``source=attachment:<id>:<name>`` label, so citation and injection contracts hold.
"""

from __future__ import annotations

import asyncio

from collections.abc import Awaitable, Callable, Sequence
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from palatium_ai.core.context.tokens import count_tokens
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.content import ContentDocument, DocumentMeta, ParagraphBlock
from palatium_ai.domain.hitl.file_choice import FileChoiceCardPolicy
from palatium_ai.domain.hitl.option_synthesis import DiscreteChoiceSynthesisPolicy
from palatium_ai.domain.memory.tool_output import (
    strip_untrusted_tool_output,
    wrap_untrusted_tool_output,
)
from palatium_ai.domain.policies.attachment_selection import AttachmentSelectionPolicy
from palatium_ai.domain.policies.locale import ReplyLocalePolicy
from palatium_ai.domain.policies.types import AttachmentKind, AttachmentScope

if TYPE_CHECKING:
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.hitl.cards import HITLCardView

logger = get_logger(__name__)

#: (untrusted file body, filename) → short factual summary. Wired to the Harness in
#: the composition root; tests pass a deterministic stub (no network, 055).
type AttachmentSummarizer = Callable[[str, str], Awaitable[str]]

#: A pending file choice has no answer yet; a deterministic refusal is certain.
_PENDING_CONFIDENCE = 0.0
_REFUSAL_CONFIDENCE = 1.0
#: A failed Map call keeps this share of the file body (per file), with a marker.
_FALLBACK_KEEP_RATIO = 0.25
_FALLBACK_MIN_CHARS = 800


class AttachmentPrepareOutcome(BaseModel):
    """Result of one preparation pass; the node maps it onto graph state."""

    model_config = {"frozen": True}

    status: Literal["unchanged", "prepared", "needs_choice"]
    blocks: tuple[AttachmentContextBlock, ...] = ()
    fenced_text: str = ""
    reduced: bool = False
    #: Only for ``needs_choice``: the turn's answer and its one-shot card.
    result: FormatterTaskResult | None = None


class AttachmentPrepareService:
    """Deterministic current-turn attachment selection + Map-Reduce budgeting."""

    def __init__(
        self,
        *,
        hitl_service: HitlService | None = None,
        summarizer: AttachmentSummarizer | None = None,
        map_reduce_threshold_tokens: int = 8_000,
        map_reduce_block_chars: int = 6_000,
    ) -> None:
        self._hitl = hitl_service
        self._summarizer = summarizer
        self._threshold_tokens = max(256, map_reduce_threshold_tokens)
        self._block_chars = max(256, map_reduce_block_chars)

    @traceable(name="attachment_prepare.prepare")
    async def prepare(
        self,
        *,
        blocks: Sequence[AttachmentContextBlock],
        task_id: str,
        thread_id: str,
        user_id: str | None,
        org_id: str | None,
        locale: str,
        ask: str,
        scope: AttachmentScope = "auto",
        kind: AttachmentKind = "any",
    ) -> AttachmentPrepareOutcome:
        """Select the ask's files and fit them into the prompt budget."""
        if not blocks:
            return AttachmentPrepareOutcome(status="unchanged")

        selection = AttachmentSelectionPolicy.select(blocks, scope=scope, kind=kind, ask=ask)
        if selection.status == "ambiguous":
            return await self._choice_outcome(
                selection.candidates,
                task_id=task_id,
                thread_id=thread_id,
                user_id=user_id,
                org_id=org_id,
                locale=locale,
                reason=selection.reason,
            )
        if selection.status == "none":
            return AttachmentPrepareOutcome(status="unchanged")

        selected = selection.blocks
        fenced = "\n\n".join(block.fenced_text for block in selected)
        reduced = await self._reduce_if_needed(selected)
        if reduced is not None:
            fenced = reduced
        logger.info(
            "attachment.prepare",
            thread_id=thread_id,
            task_id=task_id,
            reason=selection.reason,
            selected=len(selected),
            total=len(blocks),
            reduced=reduced is not None,
            fence_chars=len(fenced),
        )
        return AttachmentPrepareOutcome(
            status="prepared",
            blocks=selected,
            fenced_text=fenced,
            reduced=reduced is not None,
        )

    async def _reduce_if_needed(
        self,
        blocks: Sequence[AttachmentContextBlock],
    ) -> str | None:
        """Map each file to a summary when the joined fences exceed the threshold.

        Single-file turns keep the explicit char-budget truncation: summarizing the
        only document would discard the detail the user asked for (065).
        """
        if self._summarizer is None or len(blocks) < 2:
            return None
        joined = "\n\n".join(block.fenced_text for block in blocks)
        if count_tokens(joined) <= self._threshold_tokens:
            return None
        summaries = await asyncio.gather(
            *(self._map_block(block) for block in blocks),
            return_exceptions=True,
        )
        fences: list[str] = []
        failures = 0
        for block, summary in zip(blocks, summaries, strict=True):
            if isinstance(summary, BaseException):
                failures += 1
                logger.warning(
                    "attachment.map_reduce_failed",
                    filename=block.filename,
                    error=str(summary)[:200],
                )
                fences.append(_fallback_fence(block))
                continue
            fences.append(wrap_untrusted_tool_output(summary, source=block.source))
        if failures:
            # A degraded Map is not silent: the fences say which files were clipped.
            logger.warning("attachment.map_reduce_degraded", failed=failures, total=len(blocks))
        return "\n\n".join(fences)

    async def _map_block(self, block: AttachmentContextBlock) -> str:
        """One Map call; the body is data, the prompt is the only instruction."""
        summarizer = self._summarizer
        if summarizer is None:  # pragma: no cover - guarded by _reduce_if_needed
            raise RuntimeError("attachment summarizer is not wired")
        if not block.has_usable_text:
            return _missing_text_summary(block)
        body = strip_untrusted_tool_output(block.fenced_text).strip()
        summary = (await summarizer(body, block.filename)).strip()
        if not summary:
            return _clip_body(body, max_chars=self._block_chars)
        return summary[: self._block_chars]

    async def _choice_outcome(
        self,
        candidates: Sequence[str],
        *,
        task_id: str,
        thread_id: str,
        user_id: str | None,
        org_id: str | None,
        locale: str,
        reason: str,
    ) -> AttachmentPrepareOutcome:
        """Mint the file-choice card; the turn ends without calling a worker (020)."""
        names = FileChoiceCardPolicy.distinct_names(candidates)
        copy = _copy_for(locale)
        mintable = FileChoiceCardPolicy.mintable(names)
        actions = FileChoiceCardPolicy.build_actions(names, include_all=mintable)
        document = (
            DiscreteChoiceSynthesisPolicy.merge_actions_into_document(
                None,
                actions,
                framing_text=copy.body.format(count=len(names)),
                locale=copy.locale,
            )
            if mintable
            else _plain_document(copy=copy, count=len(names))
        )
        if self._hitl is None or not mintable:
            # No card store wired (unit graph) or one name: keep the honest
            # deterministic answer instead of letting a worker guess (020).
            return AttachmentPrepareOutcome(
                status="needs_choice",
                result=_result(task_id=task_id, document=document, card=None),
            )
        card: HITLCardView = await self._hitl.create_choice_card(
            thread_id=thread_id,
            task_id=task_id,
            title=copy.title,
            body=None,
            actions=actions,
            owner_user_id=user_id,
            org_id=org_id,
        )
        logger.info(
            "attachment.selection_card",
            thread_id=thread_id,
            task_id=task_id,
            candidates=len(names),
            reason=reason,
        )
        return AttachmentPrepareOutcome(
            status="needs_choice",
            result=_result(task_id=task_id, document=document, card=card),
        )


class _Copy(BaseModel):
    model_config = {"frozen": True}

    locale: str
    title: str
    body: str


_COPY_RU = _Copy(
    locale="ru",
    title="Какой файл нужно разобрать?",
    body=(
        "К сообщению приложено несколько файлов ({count}). Выберите один из них или «Все файлы» — "
        "я не буду угадывать, о каком документе речь."
    ),
)
_COPY_EN = _Copy(
    locale="en",
    title="Which file should I use?",
    body=("{count} files are attached to this message. Pick one or “All files” — I will not guess which document you mean."),
)


def _copy_for(locale: str) -> _Copy:
    family = ReplyLocalePolicy.locale_script_family(locale)
    return _COPY_RU if family in {"cyrillic", "weak", "other"} else _COPY_EN


def _result(
    *,
    task_id: str,
    document: ContentDocument,
    card: HITLCardView | None,
) -> FormatterTaskResult:
    pending = card is not None
    return FormatterTaskResult(
        task_id=task_id,
        agent_role="attachment_selection",
        status="partial" if pending else "failure",
        confidence=_PENDING_CONFIDENCE if pending else _REFUSAL_CONFIDENCE,
        requires_review=pending,
        output=document,
        hitl_cards=(card,) if card is not None else (),
        error=None if pending else "attachment_selection_unavailable",
    )


def _plain_document(*, copy: _Copy, count: int) -> ContentDocument:
    """Defensive fallback for a non-mintable ambiguity (one candidate)."""
    body = copy.body.format(count=count)
    return ContentDocument(
        locale=copy.locale,
        title=copy.title,
        blocks=(ParagraphBlock(text=body),),
        meta=DocumentMeta(confidence=_REFUSAL_CONFIDENCE, requires_review=False, source_refs=()),
    )


def _fallback_fence(block: AttachmentContextBlock) -> str:
    body = strip_untrusted_tool_output(block.fenced_text).strip()
    keep = max(_FALLBACK_MIN_CHARS, int(len(body) * _FALLBACK_KEEP_RATIO))
    return wrap_untrusted_tool_output(_clip_body(body, max_chars=keep), source=block.source)


def _clip_body(body: str, *, max_chars: int) -> str:
    """Explicit edge truncation; the marker makes the loss observable (065)."""
    if len(body) <= max_chars:
        return body
    omitted = len(body) - max_chars
    marker = f"\n… [file text truncated {omitted} chars — Map stage failed] …\n"
    keep = max(32, (max_chars - len(marker)) // 2)
    return f"{body[:keep]}{marker}{body[-keep:]}"


def _missing_text_summary(block: AttachmentContextBlock) -> str:
    return f"Файл «{block.filename}» приложен, но текст из него не извлечён. Содержимое недоступно; не выдумывай его."


__all__ = [
    "AttachmentPrepareOutcome",
    "AttachmentPrepareService",
    "AttachmentSummarizer",
]
