# src/palatium_ai/domain/ports/context_compact.py

"""Port for dialog summarization during ContextBuilder.compact (065)."""

from __future__ import annotations

from typing import Protocol


class DialogSummarizerPort(Protocol):
    """LLM (or test double) summarizer for dialog-only compact."""

    async def summarize_dialog(self, dialog: str) -> str:
        """Return a shorter dialog summary; must not invent facts."""
        ...
