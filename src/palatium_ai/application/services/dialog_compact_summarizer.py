# src/palatium_ai/application/services/dialog_compact_summarizer.py

"""LLM dialog summarizer for ContextBuilder.compact (065)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.domain.llm.models import ChatMessage

if TYPE_CHECKING:
    from palatium_ai.domain.ports.llm import LLMPort

_SYSTEM = """You compress a chat transcript for agent context.
Keep goals, decisions, open questions, and durable user facts.
Drop chit-chat and repeated formatting noise. Do not invent facts.
Return plain text summary only (no JSON)."""


class LlmDialogSummarizer:
    """Thin LLM adapter implementing DialogSummarizerPort."""

    def __init__(self, llm: LLMPort, *, model: str | None = None, temperature: float = 0.0) -> None:
        self._llm = llm
        self._model = model
        self._temperature = temperature

    async def summarize_dialog(self, dialog: str) -> str:
        completion = await self._llm.generate(
            [
                ChatMessage(role="system", content=_SYSTEM),
                ChatMessage(role="user", content=dialog[:120_000]),
            ],
            model=self._model,
            temperature=self._temperature,
        )
        return completion.content.strip()
