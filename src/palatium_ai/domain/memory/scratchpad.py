# src/palatium_ai/domain/memory/scratchpad.py

"""Thread-scoped session scratchpad — sync notes for the next turn (060/Anthropic).

Durable MemoryKeeper stays sleep-time. Scratchpad pins short user intents so
anaphoric follow-ups see preferences before async consolidation finishes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.recall import MemoryHit

ScratchpadSlotKind = Literal["preference", "fact"]

_SCRATCHPAD_PIN_SCORE = 10_000


class ScratchpadSlot(BaseModel):
    """One salient note for the current thread."""

    model_config = {"frozen": True}

    key: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=2000)
    kind: ScratchpadSlotKind = "fact"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class SessionScratchpad(BaseModel):
    """Bounded thread notes; always injectable into recall (query-independent)."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    slots: tuple[ScratchpadSlot, ...] = ()

    def as_memory_hits(self) -> tuple[MemoryHit, ...]:
        """Pin-first hits for Contextualizer memory_hints (high score, full confidence)."""
        return tuple(
            MemoryHit(
                text=slot.text,
                kind=slot.kind,
                confidence=slot.confidence,
                score=_SCRATCHPAD_PIN_SCORE - idx,
            )
            for idx, slot in enumerate(self.slots)
        )
