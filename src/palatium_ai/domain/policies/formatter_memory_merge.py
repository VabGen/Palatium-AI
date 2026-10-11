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
    ) -> FormatterMemoryMergeDecision:
        """Return hints to inject; empty when nothing should personalize the turn."""
        capped = max(1, min(int(max_hints), 8))
        raw = tuple(h.strip() for h in memory_hints if h and str(h).strip())
        if not raw:
            return FormatterMemoryMergeDecision(hints=(), reason="no_hints")
        if not has_source_content:
            return FormatterMemoryMergeDecision(
                hints=raw[:capped],
                reason="full_hints_no_source",
            )
        if hit_kinds is None:
            # Without kind metadata keep a small personalization slice (first N).
            return FormatterMemoryMergeDecision(
                hints=raw[: min(2, capped)],
                reason="identity_slice_with_source",
            )
        selected: list[str] = []
        for hint, kind in zip(raw, hit_kinds, strict=False):
            normalized = str(kind).strip().lower()
            if normalized in _PERSONALIZATION_KINDS:
                selected.append(hint)
            if len(selected) >= capped:
                break
        if not selected:
            # Preferences may be unlabeled; keep first hint for personalization.
            return FormatterMemoryMergeDecision(
                hints=raw[:1],
                reason="fallback_first_with_source",
            )
        return FormatterMemoryMergeDecision(
            hints=tuple(selected[:capped]),
            reason="identity_kinds_with_source",
        )
