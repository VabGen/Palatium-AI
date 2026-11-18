# src/palatium_ai/domain/policies/researcher_observation.py

"""When Researcher must JIT-re-read truncated attachment evidence (055, 065).

Anthropic context engineering 2026: do not dump larger fences into the prompt —
keep the budgeted fence and load missing spans through ``platform.read_attachment``.
Pure policy: no I/O, no LLM.
"""

from __future__ import annotations

from typing import Final

#: Hard ceiling on tool hops per Researcher turn (not unbounded ReAct).
MAX_TOOL_HOPS: Final[int] = 2

#: Explicit truncation / empty-OCR markers that mean the fence is incomplete.
_TRUNCATION_MARKERS: Final[tuple[str, ...]] = (
    "[attachment body truncated]",
    "[attachment extraction truncated]",
    "[attachment context truncated",
    "[file text truncated",
    "[mcp truncated",
    "[worker truncated",
)

#: NOTICE bodies that tell the model to call read_attachment (empty OCR path).
_EMPTY_NOTICE_MARKERS: Final[tuple[str, ...]] = (
    "текст не извлечён",
    "вызови platform.read_attachment",
    "call platform.read_attachment",
    "full text unavailable",
)


class ResearcherObservationPolicy:
    """Decide whether a ``read_attachment`` hop is required."""

    max_tool_hops: Final[int] = MAX_TOOL_HOPS

    @classmethod
    def evidence_incomplete(cls, text: str | None) -> bool:
        """True when fence/tool body carries an explicit incompleteness marker."""
        lowered = (text or "").casefold()
        if not lowered.strip():
            return False
        if any(marker in lowered for marker in _TRUNCATION_MARKERS):
            return True
        return any(marker in lowered for marker in _EMPTY_NOTICE_MARKERS)

    @classmethod
    def needs_tool_reread(
        cls,
        *,
        attached_files: str | None,
        tool_result: str | None = None,
        completed_hops: int = 0,
    ) -> bool:
        """True when another tool hop is still allowed and evidence is incomplete.

        ``completed_hops`` is the number of tool calls already finished this turn.
        """
        if completed_hops >= cls.max_tool_hops:
            return False
        return cls.evidence_incomplete(attached_files) or cls.evidence_incomplete(tool_result)

    @classmethod
    def should_force_read_plan(
        cls,
        *,
        attached_files: str | None,
        already_direct_read: bool,
    ) -> bool:
        """Planner/worker: truncated/NOTICE fences must not stay on reason_only dump."""
        if already_direct_read:
            return False
        return cls.evidence_incomplete(attached_files)


__all__ = ["MAX_TOOL_HOPS", "ResearcherObservationPolicy"]
