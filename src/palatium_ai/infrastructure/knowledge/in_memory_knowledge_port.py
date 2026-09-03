# src/palatium_ai/infrastructure/knowledge/in_memory_knowledge_port.py

"""In-memory KnowledgePort for tests and dev without Postgres knowledge schema."""

from __future__ import annotations

import re

from dataclasses import dataclass
from uuid import UUID, uuid4

from palatium_ai.domain.knowledge.types import (
    IngestDocumentCommand,
    IngestDocumentResult,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    SearchKnowledgeQuery,
)


@dataclass(frozen=True)
class _StoredChunk:
    chunk_id: UUID
    document_id: UUID
    user_id: str
    thread_id: str
    chunk_index: int
    text: str
    contextual_prefix: str
    search_text: str
    document_title: str | None


class InMemoryKnowledgePort:
    """Stores ingested documents in process memory (token-overlap search only)."""

    def __init__(self) -> None:
        self.documents: list[IngestDocumentResult] = []
        self._chunks: list[_StoredChunk] = []

    async def ingest_document(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        if not command.chunks:
            msg = "ingest_document requires at least one chunk"
            raise ValueError(msg)
        document_ref = uuid4()
        result = IngestDocumentResult(
            document_ref=document_ref,
            thread_id=command.thread_id,
            chunk_count=len(command.chunks),
        )
        self.documents.append(result)
        for chunk in command.chunks:
            prefix = chunk.contextual_prefix.strip()
            search_text = f"{prefix}\n\n{chunk.text.strip()}" if prefix else chunk.text.strip()
            self._chunks.append(
                _StoredChunk(
                    chunk_id=uuid4(),
                    document_id=document_ref,
                    user_id=command.user_id,
                    thread_id=command.thread_id,
                    chunk_index=chunk.index,
                    text=chunk.text,
                    contextual_prefix=chunk.contextual_prefix,
                    search_text=search_text,
                    document_title=command.document_title,
                )
            )
        return result

    async def search_knowledge(self, query: SearchKnowledgeQuery) -> KnowledgeSearchResult:
        cleaned = query.query.strip().lower()
        if not cleaned:
            return KnowledgeSearchResult(hits=(), query=query.query)
        tokens = {token for token in re.findall(r"[a-zA-Zа-яА-Я0-9_]{2,}", cleaned)}
        scored: list[tuple[float, _StoredChunk]] = []
        for chunk in self._chunks:
            if chunk.user_id != query.user_id:
                continue
            if query.thread_id and chunk.thread_id != query.thread_id:
                continue
            blob = chunk.search_text.lower()
            overlap = sum(1 for token in tokens if token in blob) if tokens else (1 if cleaned in blob else 0)
            if overlap > 0:
                scored.append((overlap / max(len(tokens), 1), chunk))
        scored.sort(key=lambda item: item[0], reverse=True)
        hits = tuple(
            KnowledgeSearchHit(
                chunk_id=chunk.chunk_id,
                document_id=chunk.document_id,
                chunk_index=chunk.chunk_index,
                text=chunk.text,
                contextual_prefix=chunk.contextual_prefix,
                thread_id=chunk.thread_id,
                document_title=chunk.document_title,
                score=round(min(1.0, score), 4),
            )
            for score, chunk in scored[: query.limit]
        )
        return KnowledgeSearchResult(hits=hits, query=query.query)
