# src/palatium_ai/domain/knowledge/port.py

"""KnowledgePort — static document ingest and search (060 knowledge schema)."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.knowledge.types import (
    IngestDocumentCommand,
    IngestDocumentResult,
    KnowledgeSearchResult,
    SearchKnowledgeQuery,
)


class KnowledgePort(Protocol):
    """Persist and query static knowledge (pgvector + FTS in ``knowledge`` schema)."""

    async def ingest_document(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        """Write document chunks with embeddings; idempotent per user+source_document_id optional."""

    async def search_knowledge(self, query: SearchKnowledgeQuery) -> KnowledgeSearchResult:
        """Hybrid retrieve: pgvector cosine + Postgres FTS over ``knowledge.chunks``."""
