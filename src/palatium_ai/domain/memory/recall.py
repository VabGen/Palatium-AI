# src/palatium_ai/domain/memory/recall.py

"""Budgeted long-term memory recall (anti context-dumping)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryHit(BaseModel):
    """One recalled durable memory item."""

    model_config = {"frozen": True}

    text: str = Field(min_length=1, max_length=2000)
    kind: str = Field(default="fact", max_length=32)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    score: int = Field(default=0, ge=0)


class MemoryRecallBundle(BaseModel):
    """Bounded memory packet for Contextualizer / Intent (not full dump)."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    hits: tuple[MemoryHit, ...] = ()
    max_items: int = Field(default=4, ge=1, le=8)
    max_chars: int = Field(default=800, ge=100, le=4000)

    def as_prompt_block(self) -> str:
        """Compact memory block under char/item budget."""
        if not self.hits:
            return "(no durable memory)"
        lines: list[str] = []
        used = 0
        for hit in self.hits[: self.max_items]:
            line = f"- [{hit.kind}] {hit.text.strip()}"
            if used + len(line) + 1 > self.max_chars:
                break
            lines.append(line)
            used += len(line) + 1
        return "\n".join(lines) if lines else "(no durable memory)"

    @property
    def hint_texts(self) -> tuple[str, ...]:
        """Texts only (for ContextualizerInput), under the same char budget."""
        if not self.hits:
            return ()
        texts: list[str] = []
        used = 0
        for hit in self.hits[: self.max_items]:
            text = hit.text.strip()
            if not text:
                continue
            if used + len(text) + 1 > self.max_chars and texts:
                break
            if used + len(text) + 1 > self.max_chars and not texts:
                text = text[: max(0, self.max_chars - 1)]
            texts.append(text)
            used += len(text) + 1
        return tuple(texts)
