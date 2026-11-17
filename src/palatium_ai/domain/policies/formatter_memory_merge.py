# src/palatium_ai/domain/policies/formatter_memory_merge.py

"""When Formatter keeps memory hints alongside worker source (Super Brain SB3).

Identity / preference hints must survive when ``source_content`` is present —
otherwise the model forgets the user's name after a research hop.

Kinds are closed ``MemoryType`` values only (060/010) — no invented labels.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.types import MemoryType

# Personalization kinds that should ride with worker prose (060 MemoryType SoT).
_PERSONALIZATION_KINDS: frozenset[MemoryType] = frozenset({"preference"})


class FormatterMemoryMergeDecision(BaseModel):
    """Which memory hint lines to include in the Formatter payload."""

    model_config = {"frozen": True}

    hints: tuple[str, ...] = ()
    reason: str = Field(min_length=1, max_length=128)


class FormatterMemoryMergePolicy:
    """Pure policy: merge budgeted identity hints with optional worker source."""

    @classmethod
    def decide(
        cls,
        *,
        memory_hints: tuple[str, ...] | list[str],
        has_source_content: bool,
        hit_kinds: tuple[str, ...] | list[str] | None = None,
        max_hints: int = 4,
        content_transform: bool = False,
    ) -> FormatterMemoryMergeDecision:
        """Return hints to inject; empty when nothing should personalize the turn."""
        capped = max(1, min(int(max_hints), 8))
        raw = tuple(h.strip() for h in memory_hints if h and str(h).strip())
        if not raw:
            return FormatterMemoryMergeDecision(hints=(), reason="no_hints")
        if content_transform:
            # expand/shorten/rewrite transforms prior text: a remembered topic or pinned
            # ask would let the composer answer that instead ("сравнение файлов", 055).
            return FormatterMemoryMergeDecision(
                hints=(),
                reason="content_transform_no_personalization",
            )
        if not has_source_content:
            return cls._without_source(raw, hit_kinds=hit_kinds, capped=capped)
        if hit_kinds is None:
            # Without kind metadata keep a small personalization slice (first N).
            return FormatterMemoryMergeDecision(
                hints=raw[: min(2, capped)],
                reason="identity_slice_with_source",
            )
        selected = cls._preference_hints(raw, hit_kinds, capped=capped)
        if not selected:
            # Kinds are known and none is a preference: facts/pins are not identity.
            return FormatterMemoryMergeDecision(
                hints=(),
                reason="no_personalization_kinds_with_source",
            )
        return FormatterMemoryMergeDecision(
            hints=selected,
            reason="identity_kinds_with_source",
        )

    @classmethod
    def _without_source(
        cls,
        raw: tuple[str, ...],
        *,
        hit_kinds: tuple[str, ...] | list[str] | None,
        capped: int,
    ) -> FormatterMemoryMergeDecision:
        # Social / empty-worker synthesis: without a kind gate, scratchpad asks
        # («проверь на соответствие…») become standing agendas on «привет» (055).
        if hit_kinds is None:
            return FormatterMemoryMergeDecision(
                hints=raw[:capped],
                reason="full_hints_no_source",
            )
        selected = cls._preference_hints(raw, hit_kinds, capped=capped)
        return FormatterMemoryMergeDecision(
            hints=selected,
            reason=("identity_kinds_no_source" if selected else "no_personalization_kinds_no_source"),
        )

    @staticmethod
    def _preference_hints(
        raw: tuple[str, ...],
        hit_kinds: tuple[str, ...] | list[str],
        *,
        capped: int,
    ) -> tuple[str, ...]:
        selected: list[str] = []
        for hint, kind in zip(raw, hit_kinds, strict=False):
            if str(kind).strip().lower() in _PERSONALIZATION_KINDS:
                selected.append(hint)
            if len(selected) >= capped:
                break
        return tuple(selected[:capped])
