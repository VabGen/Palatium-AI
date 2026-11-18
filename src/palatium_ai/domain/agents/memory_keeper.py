"""Контракты MemoryKeeper — sleep-time consolidation (ADD-only)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.types import MemoryType

from .contracts import TaskResult

# Extract candidates use the same closed MemoryType vocabulary as medium storage (060).
MemoryKind = MemoryType
#: Sharing tier a candidate belongs to — an axis of its own, not a content type.
#: ``kind`` says *what* the memory is; ``scope`` says *who* it is shared with (060).
MemoryScope = Literal["user", "org", "thread"]


class MemoryFactCandidate(BaseModel):
    """Один кандидат на запись в long-term memory (ADD-only)."""

    model_config = {"frozen": True}

    text: str = Field(min_length=1, max_length=2000)
    kind: MemoryKind = "fact"
    #: Namespace tier chosen by the extractor; ``None`` = legacy payload, kind-based routing.
    scope: MemoryScope | None = None
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
