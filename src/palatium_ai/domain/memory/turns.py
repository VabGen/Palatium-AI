# src/palatium_ai/domain/memory/turns.py

"""Упорядоченные реплики диалога (transcript, не long-term memory)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

DialogRole = Literal["user", "assistant", "system"]


class DialogTurn(BaseModel):
    """Одна реплика в thread."""

    model_config = {"frozen": True}

    id: UUID | None = None
    thread_id: str = Field(min_length=1, max_length=128)
    role: DialogRole
    content: str = Field(min_length=1, max_length=50_000)
    payload: dict[str, Any] | None = None
    task_id: str | None = Field(default=None, max_length=128)
    seq: int = Field(ge=0, default=0)
    created_at: datetime | None = None


class DialogTurnWindow(BaseModel):
    """Последние K реплик для Contextualizer / packet (без dump всей истории)."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    turns: tuple[DialogTurn, ...] = ()
    limit: int = Field(default=12, ge=1, le=50)

    def latest_user_content(self) -> str | None:
        """Most recent non-empty user utterance (authoritative for revision)."""
        for turn in reversed(self.turns):
            if turn.role != "user":
                continue
            content = turn.content.strip()
            if content:
                return content
        return None

    def as_prompt_block(
        self,
        *,
        max_chars: int = 12_000,
        per_turn_max_chars: int = 1200,
        user_turn_max_chars: int | None = None,
    ) -> str:
        """Компактный текст истории для LLM (newest-first char budget)."""
        if not self.turns:
            return "(no prior turns)"
        user_cap = user_turn_max_chars if user_turn_max_chars is not None else max(per_turn_max_chars, 8_000)
        selected: list[str] = []
        used = 0
        # Prefer recent turns when the window exceeds the char budget.
        for turn in reversed(self.turns):
            body = turn.content
            turn_cap = user_cap if turn.role == "user" else per_turn_max_chars
            if len(body) > turn_cap:
                body = f"{body[:turn_cap]}…"
            line = f"{turn.role}: {body}"
            extra = len(line) + (1 if selected else 0)
            if used + extra > max_chars and selected:
                break
            if used + extra > max_chars and not selected:
                prefix = f"{turn.role}: "
                room = max(0, max_chars - len(prefix) - 1)
                line = f"{prefix}{body[:room]}…"
                selected.append(line)
                break
            selected.append(line)
            used += extra
        selected.reverse()
        return "\n".join(selected)
