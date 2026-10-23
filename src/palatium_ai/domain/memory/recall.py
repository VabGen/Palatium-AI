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
    # Select tier: scratchpad | medium | graph (Super Brain SB0/SB3).
    source: str = Field(default="medium", max_length=32)


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
        return tuple(text for text, _kind in self.hint_items())

    def hint_items(self) -> tuple[tuple[str, str], ...]:
        """Budgeted ``(text, kind)`` pairs — consumers that personalise need the kind.

        Built once so ``hint_texts`` and the Formatter's kind filter cannot drift out
        of alignment on a clipped/truncated hit (065, 010).
        """
        if not self.hits:
            return ()
        items: list[tuple[str, str]] = []
        used = 0
        for hit in self.hits[: self.max_items]:
            text = hit.text.strip()
            if not text:
                continue
            if used + len(text) + 1 > self.max_chars and items:
                break
            if used + len(text) + 1 > self.max_chars and not items:
                text = text[: max(0, self.max_chars - 1)]
            items.append((text, hit.kind))
            used += len(text) + 1
        return tuple(items)

    def restrict_kinds(
        self,
        *,
        kinds: tuple[str, ...] | None = None,
        pin_kinds: tuple[str, ...] | None = None,
    ) -> MemoryRecallBundle:
        """Drop hits outside ``kinds`` (durable) / ``pin_kinds`` (scratchpad pins).

        Used when a later policy step narrows the recall axis: a content transform
        must not keep task facts or pinned asks recalled under an earlier
        ``knowledge_request`` label (055). ``None`` leaves that source unrestricted.
        """
        durable = {kind.strip().lower() for kind in kinds} if kinds is not None else None
        pinned = {kind.strip().lower() for kind in pin_kinds} if pin_kinds is not None else None
        if durable is None and pinned is None:
            return self
        kept: list[MemoryHit] = []
        for hit in self.hits:
            allowed = pinned if hit.source == "scratchpad" else durable
            if allowed is None or hit.kind.strip().lower() in allowed:
                kept.append(hit)
        if len(kept) == len(self.hits):
            return self
        return self.model_copy(update={"hits": tuple(kept)})
