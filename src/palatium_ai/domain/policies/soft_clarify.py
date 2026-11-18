# src/palatium_ai/domain/policies/soft_clarify.py

"""Soft clarify without options: answer path vs open ask (055).

When HITL synthesis cannot mint exclusive choice actions, shipping an open ask as
``success`` is wrong if the turn was answerable from attachments/prior/knowledge.
Pure policy — no I/O.
"""

from __future__ import annotations

from typing import Final

_ANSWERABLE_KINDS: Final[frozenset[str]] = frozenset(
    {
        "knowledge_request",
        "tool_execution",
        "data_analysis",
        "code_generation",
        "multi_step_workflow",
    }
)


class SoftClarifyPolicy:
    """Decide disposition when ``choice_options_missing`` and no actions."""

    @staticmethod
    def prefer_answer_path(
        *,
        task_kind: str | None,
        has_attachments: bool,
        has_prior: bool,
    ) -> bool:
        """True when the ask should be answered, not left as an open clarify ask."""
        if has_attachments or has_prior:
            return True
        kind = (task_kind or "").strip()
        return kind in _ANSWERABLE_KINDS


__all__ = ["SoftClarifyPolicy"]
