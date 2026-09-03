# src/palatium_ai/domain/memory/contextualizer.py

"""Контракты Contextualizer — rewrite / anaphora перед IntentClassifier."""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.contracts import TaskResult
from palatium_ai.domain.agents.intent import TaskKind
from palatium_ai.domain.memory.budget import MemoryPromptBudget
from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies.types import ContinuationKind

__all__ = [
    "ContinuationKind",
    "ContextualizerInput",
    "ContextualizerOutput",
    "ContextualizerTaskResult",
]


class ContextualizerInput(BaseModel):
    """Вход: сырой текст + окно диалога (+ budgeted durable memory)."""

    model_config = {"frozen": True}

    task_id: str
    user_text: str = Field(min_length=1, max_length=32_000)
    dialog_window: DialogTurnWindow
    memory_hints: tuple[str, ...] = ()
    prompt_budget: MemoryPromptBudget = Field(default_factory=MemoryPromptBudget)
    task_kind: TaskKind | None = None
    requires_mcp: bool = False


class ContextualizerOutput(BaseModel):
    """Standalone rewrite + тип продолжения."""

    model_config = {"frozen": True}

    rewritten_query: str = Field(min_length=1, max_length=32_000)
    continuation_kind: ContinuationKind
    confidence: float = Field(ge=0.0, le=1.0)
    refers_to_prior: bool = False
    prior_assistant_excerpt: str | None = Field(default=None, max_length=4000)
    reasoning: str = Field(min_length=1, max_length=2000)
    # True when this turn is a completed HITL user_choice pick (deterministic resume).
    choice_slot_filled: bool = False


class ContextualizerTaskResult(TaskResult):
    """TaskResult Contextualizer."""

    output: ContextualizerOutput | None = None
