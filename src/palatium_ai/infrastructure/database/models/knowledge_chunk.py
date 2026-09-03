# src/palatium_ai/infrastructure/database/models/knowledge_chunk.py

"""Static knowledge ORM — schema ``knowledge`` (060)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from palatium_ai.core.types.embeddings import KNOWLEDGE_EMBEDDING_DIM
from palatium_ai.infrastructure.database.base import Base, UUIDPrimaryKeyMixin

KNOWLEDGE_SCHEMA = "knowledge"


class KnowledgeDocumentORM(UUIDPrimaryKeyMixin, Base):
    """Ingested document metadata."""

    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_knowledge_documents_user_thread", "user_id", "thread_id"),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_document_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    mime_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeChunkORM(UUIDPrimaryKeyMixin, Base):
    """Searchable knowledge chunk with contextual prefix for embedding."""

    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_doc_index"),
        {"schema": KNOWLEDGE_SCHEMA},
    )

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey(f"{KNOWLEDGE_SCHEMA}.documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    contextual_prefix: Mapped[str] = mapped_column(Text, nullable=False, default="")
    char_start: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    search_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    embedding: Mapped[list[float] | None] = mapped_column(Vector(KNOWLEDGE_EMBEDDING_DIM), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
