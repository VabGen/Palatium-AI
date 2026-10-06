# src/palatium_ai/domain/policies/graph_fact.py

"""Supersede / conflict policy for long-term MemoryFact (Wave M5 / ADR 0004)."""

from __future__ import annotations

from typing import Literal

GraphFactWriteAction = Literal["create", "refresh", "supersede", "blocked_pii"]


class GraphFactPolicy:
    """Pure decision: silent text overwrite is never allowed."""

    @staticmethod
    def decide_write(
        *,
        existing_text: str | None,
        new_text: str,
        contains_pii: bool,
    ) -> GraphFactWriteAction:
        """Choose create / refresh / supersede / blocked_pii for an active fact."""
        incoming = new_text.strip()
        if not incoming:
            msg = "new fact text must be non-empty"
            raise ValueError(msg)
        if existing_text is None:
            return "create"
        prior = existing_text.strip()
        if prior == incoming:
            return "refresh"
        # High-risk semantic flip on PII requires HITL — batch promote must not auto-flip.
        if contains_pii:
            return "blocked_pii"
        return "supersede"
