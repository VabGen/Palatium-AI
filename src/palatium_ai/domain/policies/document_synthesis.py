# src/palatium_ai/domain/policies/document_synthesis.py

"""Chunked (map-reduce) synthesis for evidence larger than one prompt.

A 40-page contract must not be answered from its first 12k characters: the
recommendations would silently describe only the opening section. The policy is
deterministic — it decides *whether* to shard, *where* to cut, and *how many*
calls the turn may spend; the agent owns the prompts (030, 055, 065).
"""

from __future__ import annotations

from dataclasses import dataclass

#: A cut prefers a paragraph / sentence boundary inside this tail share of a chunk.
_SOFT_BOUNDARY_RATIO = 0.15
#: Paragraph break first, then line break, then sentence end — longest wins.
_BOUNDARY_MARKERS: tuple[str, ...] = ("\n\n", "\n", ". ", "! ", "? ", "; ")


@dataclass(frozen=True)
class SynthesisChunk:
    """One slice of the evidence body for a map call."""

    index: int
    start: int
    end: int

    @property
    def chars(self) -> int:
        return self.end - self.start


class DocumentSynthesisPolicy:
    """Plan for reading a long document in bounded pieces (065).

    ``needs_chunking`` compares the body against the per-call budget that the
    prompt already enforces; ``plan`` shards it into at most ``max_chunks``
    slices, so cost stays predictable (080).
    """

    @staticmethod
    def needs_chunking(*, body_chars: int, budget_chars: int) -> bool:
        if budget_chars <= 0:
            return False
        return body_chars > budget_chars

    @classmethod
    def plan(
        cls,
        text: str,
        *,
        budget_chars: int,
        max_chunks: int,
    ) -> tuple[SynthesisChunk, ...]:
        """Return contiguous, non-empty slices covering the whole body.

        Chunk size is the budget, raised to ``ceil(len/max_chunks)`` when the
        budget alone would exceed the call ceiling. Boundaries prefer paragraph
        or sentence ends so a requirement is not split across two map calls.
        """
        body_chars = len(text)
        if body_chars <= 0:
            return ()
        if not cls.needs_chunking(body_chars=body_chars, budget_chars=budget_chars):
            return (SynthesisChunk(index=0, start=0, end=body_chars),)

        limit = max(1, max_chunks)
        size = max(budget_chars, -(-body_chars // limit))
        chunks: list[SynthesisChunk] = []
        start = 0
        index = 0
        while start < body_chars:
            end = min(body_chars, start + size)
            if end < body_chars:
                end = cls._soft_end(text, start=start, end=end, size=size)
            chunks.append(SynthesisChunk(index=index, start=start, end=end))
            start = end
            index += 1
        return tuple(chunks)

    @staticmethod
    def _soft_end(text: str, *, start: int, end: int, size: int) -> int:
        """Pull the cut back to the nearest boundary inside the tail window."""
        window = max(1, int(size * _SOFT_BOUNDARY_RATIO))
        floor = max(start + 1, end - window)
        for marker in _BOUNDARY_MARKERS:
            at = text.rfind(marker, floor, end)
            if at != -1:
                return at + len(marker)
        return end


__all__ = [
    "DocumentSynthesisPolicy",
    "SynthesisChunk",
]
