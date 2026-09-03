# src/palatium_ai/domain/knowledge/types.py

"""Knowledge ingest and search contracts (static knowledge schema, 060)."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.agents.text_ingestor import TextChunk


class IngestDocumentResult(BaseModel):
    """Result of persisting ingested document chunks into ``knowledge`` schema."""

    model_config = {"frozen": True}

    document_ref: UUID
    thread_id: str
    chunk_count: int = Field(ge=0)
    status: str = "ingested"


class IngestDocumentCommand(BaseModel):
    """Command to persist prepared chunks (after HITL when required)."""

    model_config = {"frozen": True}

    user_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    document_id: str | None = Field(default=None, max_length=128)
    document_title: str | None = Field(default=None, max_length=256)
    mime_type: str | None = Field(default=None, max_length=128)
    chunks: tuple[TextChunk, ...] = ()


class SearchKnowledgeQuery(BaseModel):
    """Hybrid search over ``knowledge.chunks`` (pgvector + FTS)."""

    model_config = {"frozen": True}

    user_id: str = Field(min_length=1, max_length=128)
    query: str = Field(min_length=1, max_length=500)
    thread_id: str | None = Field(default=None, max_length=128)
    limit: int = Field(default=8, ge=1, le=32)


class KnowledgeSearchHit(BaseModel):
    """One ranked knowledge chunk hit."""

    model_config = {"frozen": True}

    chunk_id: UUID
    document_id: UUID
    chunk_index: int = Field(ge=0)
    text: str
    contextual_prefix: str = ""
    thread_id: str
    document_title: str | None = None
    score: float = Field(ge=0.0, le=1.0)


class KnowledgeSearchResult(BaseModel):
    """Ranked hybrid search results."""

    model_config = {"frozen": True}

    hits: tuple[KnowledgeSearchHit, ...] = ()
    query: str
