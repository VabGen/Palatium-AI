# src/palatium_ai/domain/agents/memory_keeper.py

"""Контракты MemoryKeeper — sleep-time consolidation (ADD-only)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import TaskResult

MemoryKind = Literal["fact", "preference", "entity", "summary"]


class MemoryFactCandidate(BaseModel):
    """Один кандидат на запись в long-term memory (ADD-only)."""

    model_config = {"frozen": True}

    text: str = Field(min_length=1, max_length=2000)
    kind: MemoryKind = "fact"
    confidence: float = Field(ge=0.0, le=1.0)
    key_hint: str | None = Field(default=None, max_length=128)


class MemoryKeeperInput(BaseModel):
    """Вход sleep-time консолидации (не hot path)."""

    model_config = {"frozen": True}

    task_id: str
    thread_id: str
    transcript_excerpt: str = Field(min_length=1, max_length=12000)
    existing_memory_texts: tuple[str, ...] = ()


class MemoryKeeperOutput(BaseModel):
    """ADD-only кандидаты; пустой список = нечего сохранять."""

    model_config = {"frozen": True}

    facts: tuple[MemoryFactCandidate, ...] = ()
    reasoning: str = Field(default="", max_length=1000)


class MemoryKeeperTaskResult(TaskResult):
    """TaskResult MemoryKeeper."""

    output: MemoryKeeperOutput | None = None
