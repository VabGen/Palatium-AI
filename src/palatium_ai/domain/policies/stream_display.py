# src/palatium_ai/domain/policies/stream_display.py

"""Per-block display strategy while a ``ContentDocument`` streams (W1, 055).

``structured_incremental`` paints every ``blocks[]`` element when it closes. That is
correct but late: a long paragraph is readable as it arrives, so waiting for the
closing brace throws away the perception of progress. The fix is not "stream
everything" — a half-filled table, a truncated ``code`` body or a list that grows row
by row is worse than a reserved placeholder, because the user starts reading data
that is not there yet.

So the decision "may this element show partial content" is a domain policy keyed by
block type, owned here and nowhere else (050): the incremental scanner asks, the
client renders according to the same answer, and no module re-derives it from a
hand-written ``if``.

Why the answer differs per type:

* ``paragraph`` — a prefix is a sentence in progress; reading it early is the useful
  experience the whole streaming contract exists for.
* ``list`` / ``steps`` / ``table`` / ``kv`` / ``chart`` — the element's meaning is the
  *set* of rows. One row of a comparison table reads as the answer.
* ``code`` / ``formula`` — partial content is misinformation: an incomplete expression
  is syntactically and semantically different from the real one.
* ``heading`` / ``callout`` / ``divider`` / ``widget`` — short or atomic; nothing is
  gained by painting them before they validate.

``skeleton`` and ``on_close`` are both "no partial content" on the wire: whether the
client reserves a placeholder shape or nothing is a rendering decision that belongs to
the client (a block that has not arrived has no type yet).
"""

from __future__ import annotations

from typing import Final

from palatium_ai.domain.policies.types import StreamDisplay

#: Closed mapping: every ``ContentBlock.type`` value is listed exactly once, so a new
#: block type cannot silently inherit a strategy by omission.
_STRATEGY: Final[dict[str, StreamDisplay]] = {
    "paragraph": "text_delta",
    "list": "skeleton",
    "steps": "skeleton",
    "table": "skeleton",
    "kv": "skeleton",
    "chart": "skeleton",
    "heading": "on_close",
    "callout": "on_close",
    "code": "on_close",
    "formula": "on_close",
    "divider": "on_close",
    "widget": "on_close",
}


class StreamDisplayPolicy:
    """Pure lookup from block type to its streaming strategy."""

    @classmethod
    def strategy_for(cls, block_type: str) -> StreamDisplay:
        """Strategy for ``block_type``; unknown types wait for close (fail-safe)."""
        return _STRATEGY.get((block_type or "").strip().lower(), "on_close")

    @classmethod
    def partial_prose_allowed(cls, block_type: str) -> bool:
        """True only when an open element may paint its prose incrementally."""
        return cls.strategy_for(block_type) == "text_delta"


__all__ = ["StreamDisplayPolicy"]
