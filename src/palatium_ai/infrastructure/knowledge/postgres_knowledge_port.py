# src/palatium_ai/infrastructure/knowledge/postgres_knowledge_port.py

"""Postgres-backed KnowledgePort against ``knowledge.documents`` / ``knowledge.chunks``."""

from __future__ import annotations

import json
import re
import time

from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import Float, cast, func, or_, select
from sqlalchemy.orm import aliased

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.security.secret_scanner import scan_text
from palatium_ai.core.types.embeddings import assert_vector_dim
from palatium_ai.domain.knowledge.scoring import merge_hybrid_knowledge_hits
from palatium_ai.domain.knowledge.types import (
    IngestDocumentCommand,
    IngestDocumentResult,
    KnowledgeSearchHit,
    KnowledgeSearchResult,
    SearchKnowledgeQuery,
)
from palatium_ai.infrastructure.database.models.knowledge_chunk import KnowledgeChunkORM, KnowledgeDocumentORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.domain.ports.embeddings import EmbeddingPort


def _chunk_search_text(*, contextual_prefix: str, body: str) -> str:
    prefix = contextual_prefix.strip()
    if prefix:
        return f"{prefix}\n\n{body.strip()}"
    return body.strip()


class PostgresKnowledgePort:
    """Persist ingested document chunks with knowledge-schema embeddings (1536d)."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embeddings: EmbeddingPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embeddings = embeddings

    async def ingest_document(self, command: IngestDocumentCommand) -> IngestDocumentResult:
        if not command.chunks:
            msg = "ingest_document requires at least one chunk"
            raise ValueError(msg)

        search_texts: list[str] = []
        for chunk in command.chunks:
            blob = _chunk_search_text(contextual_prefix=chunk.contextual_prefix, body=chunk.text)
            scan_text(blob, field="knowledge_chunk")
            search_texts.append(blob)

        vectors: list[list[float]] = []
        if self._embeddings is not None:
            vectors = await self._embeddings.embed(search_texts)
            for vector in vectors:
                assert_vector_dim(schema="knowledge", vector_len=len(vector))

        now = datetime.now(UTC)
        document_id = uuid4()
        async with self._session_factory() as session:
            await set_rls_user_scope(session, command.user_id)
            session.add(
                KnowledgeDocumentORM(
                    id=document_id,
                    user_id=command.user_id,
                    thread_id=command.thread_id,
                    source_document_id=command.document_id,
                    title=command.document_title,
                    mime_type=command.mime_type,
                    chunk_count=len(command.chunks),
                    created_at=now,
                    updated_at=now,
                )
            )
            for index, chunk in enumerate(command.chunks):
                embedding = vectors[index] if index < len(vectors) else None
                session.add(
                    KnowledgeChunkORM(
                        id=uuid4(),
                        document_id=document_id,
                        user_id=command.user_id,
                        chunk_index=chunk.index,
                        text=chunk.text,
                        contextual_prefix=chunk.contextual_prefix,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        search_text=search_texts[index],
                        embedding=embedding,
                        created_at=now,
                    )
                )
            await session.commit()

        agent_metrics.record_memory_entry_size(
            memory_type="knowledge_chunk",
            size_bytes=len(json.dumps([chunk.text for chunk in command.chunks], ensure_ascii=False).encode("utf-8")),
        )
        return IngestDocumentResult(
            document_ref=document_id,
            thread_id=command.thread_id,
            chunk_count=len(command.chunks),
        )

    async def search_knowledge(self, query: SearchKnowledgeQuery) -> KnowledgeSearchResult:
        cleaned = query.query.strip()
        if not cleaned:
            return KnowledgeSearchResult(hits=(), query=query.query)

        safe_limit = max(1, min(query.limit, 32))
        started = time.perf_counter()
        try:
            fts_hits = await self._search_fts(
                user_id=query.user_id,
                thread_id=query.thread_id,
                query=cleaned,
                limit=safe_limit,
            )
            vector_hits: list[tuple[str, float, dict[str, object]]] = []
            if self._embeddings is not None:
                vector_hits = await self._search_vector(
                    user_id=query.user_id,
                    thread_id=query.thread_id,
                    query=cleaned,
                    limit=safe_limit,
                )
            if fts_hits or vector_hits:
                raw_hits = merge_hybrid_knowledge_hits(fts_hits, vector_hits, limit=safe_limit)
            else:
                raw_hits = await self._search_token_overlap(
                    user_id=query.user_id,
                    thread_id=query.thread_id,
                    query=cleaned,
                    limit=safe_limit,
                )
            return KnowledgeSearchResult(
                hits=tuple(_hit_from_payload(item) for item in raw_hits),
                query=query.query,
            )
        finally:
            agent_metrics.record_memory_query_duration(time.perf_counter() - started)

    async def _search_fts(
        self,
        *,
        user_id: str,
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[tuple[str, float, dict[str, object]]]:
        doc = aliased(KnowledgeDocumentORM)
        ts_vector = func.to_tsvector("simple", KnowledgeChunkORM.search_text)
        ts_query = func.plainto_tsquery("simple", query)
        rank = cast(func.ts_rank_cd(ts_vector, ts_query), Float)
        filters = [KnowledgeChunkORM.user_id == user_id, ts_vector.op("@@")(ts_query)]
        if thread_id:
            filters.append(doc.thread_id == thread_id)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(KnowledgeChunkORM, doc, rank.label("rank"))
                .join(doc, KnowledgeChunkORM.document_id == doc.id)
                .where(*filters)
                .order_by(rank.desc())
                .limit(limit)
            )
            rows = result.all()
        return [
            (
                str(chunk.id),
                float(score or 0.0),
                _chunk_payload(chunk, document),
            )
            for chunk, document, score in rows
        ]

    async def _search_vector(
        self,
        *,
        user_id: str,
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[tuple[str, float, dict[str, object]]]:
        if self._embeddings is None:
            msg = "vector search requires embeddings client"
            raise RuntimeError(msg)
        vectors = await self._embeddings.embed([query])
        if not vectors:
            return []
        query_vec = vectors[0]
        assert_vector_dim(schema="knowledge", vector_len=len(query_vec))
        doc = aliased(KnowledgeDocumentORM)
        distance = KnowledgeChunkORM.embedding.cosine_distance(query_vec)
        similarity = (1.0 - distance).label("similarity")
        filters = [
            KnowledgeChunkORM.user_id == user_id,
            KnowledgeChunkORM.embedding.is_not(None),
        ]
        if thread_id:
            filters.append(doc.thread_id == thread_id)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(KnowledgeChunkORM, doc, similarity)
                .join(doc, KnowledgeChunkORM.document_id == doc.id)
                .where(*filters)
                .order_by(distance.asc())
                .limit(limit)
            )
            rows = result.all()
        return [
            (
                str(chunk.id),
                max(0.0, float(score or 0.0)),
                _chunk_payload(chunk, document),
            )
            for chunk, document, score in rows
        ]

    async def _search_token_overlap(
        self,
        *,
        user_id: str,
        thread_id: str | None,
        query: str,
        limit: int,
    ) -> list[dict[str, object]]:
        tokens = {token for token in re.findall(r"[a-zA-Zа-яА-Я0-9_]{2,}", query.lower())}
        doc = aliased(KnowledgeDocumentORM)
        filters = [KnowledgeChunkORM.user_id == user_id]
        if thread_id:
            filters.append(doc.thread_id == thread_id)
        if tokens:
            filters.append(or_(*[KnowledgeChunkORM.search_text.ilike(f"%{token}%") for token in list(tokens)[:8]]))
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(KnowledgeChunkORM, doc)
                .join(doc, KnowledgeChunkORM.document_id == doc.id)
                .where(*filters)
                .limit(limit * 4)
            )
            rows = result.all()
        scored: list[tuple[float, dict[str, object]]] = []
        for chunk, document in rows:
            blob = chunk.search_text.lower()
            overlap = sum(1 for token in tokens if token in blob)
            if not tokens or overlap > 0:
                scored.append((overlap / max(len(tokens), 1), _chunk_payload(chunk, document)))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [_with_overlap_score(payload, score) for score, payload in scored[:limit]]


def _chunk_payload(chunk: KnowledgeChunkORM, document: KnowledgeDocumentORM) -> dict[str, object]:
    return {
        "chunk_id": str(chunk.id),
        "document_id": str(chunk.document_id),
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "contextual_prefix": chunk.contextual_prefix,
        "thread_id": document.thread_id,
        "document_title": document.title,
    }


def _hit_from_payload(payload: dict[str, object]) -> KnowledgeSearchHit:
    score_raw = payload.get("score", 0.0)
    chunk_index_raw = payload["chunk_index"]
    return KnowledgeSearchHit(
        chunk_id=UUID(str(payload["chunk_id"])),
        document_id=UUID(str(payload["document_id"])),
        chunk_index=int(str(chunk_index_raw)),
        text=str(payload["text"]),
        contextual_prefix=str(payload.get("contextual_prefix", "")),
        thread_id=str(payload["thread_id"]),
        document_title=str(payload["document_title"]) if payload.get("document_title") else None,
        score=float(str(score_raw)),
    )


def _with_overlap_score(payload: dict[str, object], score: float) -> dict[str, object]:
    enriched = dict(payload)
    enriched["score"] = round(min(1.0, max(0.0, score)), 4)
    return enriched
