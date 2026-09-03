# src/palatium_ai/domain/agents/text_ingestor.py

"""Контракты TextIngestor — чанкинг и нормализация при ингесте (off hot path)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from .contracts import TaskResult

ChunkingStrategy = Literal["paragraph", "fixed_window"]


class TextChunk(BaseModel):
    """Один чанк для последующего embed / ingest_document."""

    model_config = {"frozen": True}

    index: int = Field(ge=0)
    text: str = Field(min_length=1)
    char_start: int = Field(ge=0)
    char_end: int = Field(gt=0)
    contextual_prefix: str = Field(default="", max_length=500)


class TextIngestorInput(BaseModel):
    """Вход подготовки текста к ингесту (не LangGraph hot path)."""

    model_config = {"frozen": True}

    task_id: str
    thread_id: str
    document_id: str | None = Field(default=None, max_length=128)
    raw_text: str = Field(min_length=1, max_length=500_000)
    mime_type: str | None = Field(default=None, max_length=128)
    locale: str | None = Field(default=None, max_length=16)
    max_chunk_chars: int = Field(default=1500, gt=0, le=8000)
    enrich_context_prefix: bool = False
    document_title: str | None = Field(default=None, max_length=256)


class TextIngestorOutput(BaseModel):
    """Нормализованные чанки; ingest_document вызывается отдельно (HITL, 020)."""

    model_config = {"frozen": True}

    chunks: tuple[TextChunk, ...] = ()
    chunking_strategy: ChunkingStrategy = "paragraph"
    normalized_char_count: int = Field(ge=0)
    context_prefixes_applied: bool = False


class TextIngestorTaskResult(TaskResult):
    """TaskResult TextIngestor."""

    output: TextIngestorOutput | None = None
