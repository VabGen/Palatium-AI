# src/palatium_ai/domain/memory/budget.py

"""Char/item budgets for Contextualizer prompts (anti context-dumping)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryPromptBudget(BaseModel):
    """Hard caps for dialog + durable memory injected into Contextualizer."""

    model_config = {"frozen": True}

    dialog_max_chars: int = Field(default=12_000, ge=500, le=32_000)
    per_turn_max_chars: int = Field(default=1200, ge=200, le=8000)
    # User turns carry task payloads (pasted docs); assistant stays tight.
    user_turn_max_chars: int = Field(default=8_000, ge=500, le=32_000)
    memory_max_items: int = Field(default=4, ge=1, le=8)
    memory_max_chars: int = Field(default=800, ge=100, le=4000)
    prior_excerpt_max_chars: int = Field(default=1500, ge=100, le=16_000)
    worker_summary_max_chars: int = Field(default=8_000, ge=500, le=16_000)
    mcp_tool_output_max_chars: int = Field(default=3000, ge=500, le=16_000)


DEFAULT_PROMPT_BUDGET = MemoryPromptBudget()


def clip_memory_hints(
    hints: tuple[str, ...] | list[str],
    *,
    max_items: int = DEFAULT_PROMPT_BUDGET.memory_max_items,
    max_chars: int = DEFAULT_PROMPT_BUDGET.memory_max_chars,
) -> tuple[str, ...]:
    """Keep highest-priority hints under item/char budget (order preserved)."""
    selected: list[str] = []
    used = 0
    for raw in hints[:max_items]:
        text = raw.strip()
        if not text:
            continue
        if used + len(text) + 1 > max_chars and selected:
            break
        if used + len(text) + 1 > max_chars and not selected:
            text = text[: max(0, max_chars - 1)]
        selected.append(text)
        used += len(text) + 1
    return tuple(selected)
