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
            if isinstance(block, ParagraphBlock) and _CURRENT_SESSION_CLAIM.search(block.text):
                text = cls._rewrite_claim(block.text)
                new_blocks.append(block.model_copy(update={"text": text}))
                changed = True
                continue
            if isinstance(block, CalloutBlock):
                body = block.body or ""
                title = block.title or ""
                if _CURRENT_SESSION_CLAIM.search(body) or _CURRENT_SESSION_CLAIM.search(title):
                    new_body = cls._rewrite_claim(body) if _CURRENT_SESSION_CLAIM.search(body) else body
                    new_title = _CURRENT_SESSION_CLAIM.sub("", title).strip() or block.title
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

    @staticmethod
    def _rewrite_claim(text: str) -> str:
        rewritten = _CURRENT_SESSION_CLAIM.sub(_MEMORY_REPLACEMENT_RU, text).strip()
        return rewritten or _MEMORY_REPLACEMENT_RU


__all__ = ["MEMORY_SOURCE_MARKER", "AttributionPolicy"]
