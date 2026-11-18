# src/palatium_ai/domain/policies/attribution.py

"""Rewrite false «current session» claims when the fact came from medium memory (W10.1 P0.2).

Recall into a *new* thread must not be narrated as dialog-window context. The
Formatter sometimes invents «в контексте текущей сессии» for medium hits; that
is an attribution bug, not a recall bug (055: fix the contract, not the phrase
list of user asks). Structural rewrite only — we never suppress the fact itself.
"""

from __future__ import annotations

import re

from typing import TYPE_CHECKING

from palatium_ai.domain.content import CalloutBlock, ContentDocument, ParagraphBlock

if TYPE_CHECKING:
    from collections.abc import Sequence

#: Product-emitted false frames (RU/EN). Not a user-ask classifier — known
#: Formatter/Researcher slips when medium recall lands in a *new* thread (W10 §5).
_CURRENT_SESSION_CLAIM = re.compile(
    r"(?:"
    r"[Вв]\s+контексте\s+текущей\s+сессии"
    r"|[Вв]\s+текущ(?:ей|ем)\s+(?:сессии|диалоге|чате)"
    r"|[Вв]\s+этом\s+(?:диалоге|чате|сессии)"
    r"|in\s+(?:the\s+)?(?:current|this)\s+(?:session|dialog(?:ue)?|chat|thread)"
    r")[^.?!\n]*[.?!]?",
    flags=re.UNICODE | re.IGNORECASE,
)
#: File-inventory / re-read refusals also say «в этом диалоге», but that is
#: dialog *attachment* state — not a medium-recall frame. Rewriting them stopped
#: at the ``.`` inside ``.pdf`` and turned the refusal into
#: «Из сохранённой памяти….pdf», «ht_1-5.webp»… (055 / living assistant).
_STRUCTURAL_DIALOG_FILE_STATE = re.compile(
    r"[Вв]\s+этом\s+диалоге\s+"
    r"(?:несколько\s+(?:подходящих\s+)?файлов|нет\s+загруженных\s+файлов)",
    flags=re.UNICODE,
)
#: Wire-format provenance stamp. Clients must not render it as a file chip
#: (see ``displaySourceRefs`` / ``isInternalSourceRef`` in ``web/src/lib/attachments.ts``).
MEMORY_SOURCE_MARKER = "from memory"
_MEMORY_MARKER = MEMORY_SOURCE_MARKER
_MEMORY_REPLACEMENT_RU = "Из сохранённой памяти (не из текущего диалога)."


class AttributionPolicy:
    """Pure post-process: mark medium-sourced answers; never invent facts."""

    @classmethod
    def rewrite_false_current_session(
        cls,
        document: ContentDocument,
        *,
        memory_hints: Sequence[str] = (),
    ) -> ContentDocument:
        """If medium hints grounded the turn, strip false «current session» framing."""
        if not memory_hints:
            return document
        changed = False
        new_blocks: list[object] = []
        for block in document.blocks:
            if isinstance(block, ParagraphBlock) and cls._claim_needs_rewrite(block.text):
                text = cls._rewrite_claim(block.text)
                new_blocks.append(block.model_copy(update={"text": text}))
                changed = True
                continue
            if isinstance(block, CalloutBlock):
                body = block.body or ""
                title = block.title or ""
                body_needs = cls._claim_needs_rewrite(body)
                title_needs = cls._claim_needs_rewrite(title)
                if body_needs or title_needs:
                    new_body = cls._rewrite_claim(body) if body_needs else body
                    new_title = (_CURRENT_SESSION_CLAIM.sub("", title).strip() or block.title) if title_needs else block.title
                    new_blocks.append(block.model_copy(update={"body": new_body, "title": new_title}))
                    changed = True
                    continue
            new_blocks.append(block)
        refs = document.meta.source_refs
        if _MEMORY_MARKER not in refs:
            refs = (*refs, _MEMORY_MARKER)
            changed = True
        if not changed:
            return document
        meta = document.meta.model_copy(update={"source_refs": refs})
        return document.model_copy(update={"blocks": tuple(new_blocks), "meta": meta})

    @classmethod
    def _claim_needs_rewrite(cls, text: str) -> bool:
        """True only for false session frames — not structural file-inventory lines."""
        if not text or _STRUCTURAL_DIALOG_FILE_STATE.search(text):
            return False
        return _CURRENT_SESSION_CLAIM.search(text) is not None

    @staticmethod
    def _rewrite_claim(text: str) -> str:
        if _STRUCTURAL_DIALOG_FILE_STATE.search(text):
            return text
        rewritten = _CURRENT_SESSION_CLAIM.sub(_MEMORY_REPLACEMENT_RU, text).strip()
        return rewritten or _MEMORY_REPLACEMENT_RU


__all__ = ["MEMORY_SOURCE_MARKER", "AttributionPolicy"]
