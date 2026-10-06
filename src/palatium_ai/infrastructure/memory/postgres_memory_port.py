# src/palatium_ai/infrastructure/memory/postgres_memory_port.py

"""Postgres-backed MemoryPort against ``memory.entries`` (060)."""

from __future__ import annotations

import json
import re
import time

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, cast, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.core.types.embeddings import assert_vector_dim
from palatium_ai.domain.memory.pii import mask_memory_value
from palatium_ai.domain.memory.promotion import PromotionCandidate
from palatium_ai.domain.memory.types import MemoryType
from palatium_ai.infrastructure.database.models.memory_entry import MemoryEntryORM
from palatium_ai.infrastructure.database.rls import set_rls_user_scope
from palatium_ai.infrastructure.memory.user_scope import resolve_user_id

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.domain.ports.embeddings import EmbeddingPort

_VALID_MEMORY_TYPES: frozenset[str] = frozenset({"preference", "fact", "incident", "episode"})


def encode_namespace(namespace: tuple[str, ...]) -> str:
    """Stable string key for namespace tuple."""
    return "/".join(part.replace("/", "_") for part in namespace)


def decode_namespace(encoded: str) -> tuple[str, ...]:
    """Inverse of encode_namespace for slash-separated namespaces without embedded ``/``."""
    if not encoded:
        return ()
    return tuple(encoded.split("/"))


def normalize_memory_type(value: dict[str, object]) -> MemoryType:
    """Map stored value kind to canonical MemoryType."""
    raw = str(value.get("kind", "fact")).strip().lower()
    if raw in _VALID_MEMORY_TYPES:
        return raw  # type: ignore[return-value]  # membership не сужает str→MemoryType (017)
    return "fact"


def merge_hybrid_scores(
    fts_hits: list[tuple[str, float, dict[str, object]]],
    vector_hits: list[tuple[str, float, dict[str, object]]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    """Merge FTS and vector hits by entry key; keep max blended score."""
    merged: dict[str, tuple[float, dict[str, object]]] = {}
    for entry_key, score, payload in fts_hits + vector_hits:
        current = merged.get(entry_key)
        blended = score * (0.5 + 0.5 * _value_confidence(payload))
        if current is None or blended > current[0]:
            merged[entry_key] = (blended, payload)
    ranked = sorted(merged.values(), key=lambda item: item[0], reverse=True)
    return [
        _with_score(payload, score, entry_key=str(payload.get("_entry_key", ""))) for score, payload in ranked[:limit]
    ]


class PostgresMemoryPort:
    """Implements MemoryPort against ``memory.entries`` with user_id scope + hybrid search."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        embeddings: EmbeddingPort | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._embeddings = embeddings

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        """Upsert a memory item under namespace/key."""
        user_id = resolve_user_id(namespace, value)
        ns = encode_namespace(namespace)
        search_blob = _search_blob(value)
        memory_type = normalize_memory_type(value)
        importance = max(0.0, min(1.0, coerce_float(value.get("importance", value.get("confidence", 0.0)))))
        contains_pii = bool(value.get("contains_pii", False))
        embedding: list[float] | None = None
        if self._embeddings is not None and search_blob.strip():
            vectors = await self._embeddings.embed([search_blob])
            if vectors:
                embedding = vectors[0]
                assert_vector_dim(schema="memory", vector_len=len(embedding))

        agent_metrics.record_memory_entry_size(
            memory_type=memory_type,
            size_bytes=len(json.dumps(value, ensure_ascii=False).encode("utf-8")),
        )

        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            stmt = (
                insert(MemoryEntryORM)
                .values(
                    user_id=user_id,
                    namespace=ns,
                    entry_key=key,
                    memory_type=memory_type,
                    value=value,
                    search_text=search_blob,
                    importance=importance,
                    contains_pii=contains_pii,
                    embedding=embedding,
                )
                .on_conflict_do_update(
                    constraint="uq_memory_entries_user_ns_key",
                    set_={
                        "value": value,
                        "search_text": search_blob,
                        "memory_type": memory_type,
                        "importance": importance,
                        "contains_pii": contains_pii,
                        "embedding": embedding,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        """Fetch one item or None."""
        user_id = resolve_user_id(namespace)
        ns = encode_namespace(namespace)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(MemoryEntryORM).where(
                    MemoryEntryORM.user_id == user_id,
                    MemoryEntryORM.namespace == ns,
                    MemoryEntryORM.entry_key == key,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return mask_memory_value(dict(row.value), contains_pii=row.contains_pii)

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Hybrid retrieve: pgvector cosine + Postgres FTS, ranked by importance."""
        user_id = resolve_user_id(namespace)
        ns = encode_namespace(namespace)
        safe_limit = max(1, min(limit, 32))
        cleaned = query.strip()
        if not cleaned:
            return []

        started = time.perf_counter()
        try:
            fts_hits = await self._search_fts(user_id=user_id, namespace=ns, query=cleaned, limit=safe_limit)
            vector_hits: list[tuple[str, float, dict[str, object]]] = []
            if self._embeddings is not None:
                vector_hits = await self._search_vector(
                    user_id=user_id,
                    namespace=ns,
                    query=cleaned,
                    limit=safe_limit,
                )
            if fts_hits or vector_hits:
                return merge_hybrid_scores(fts_hits, vector_hits, limit=safe_limit)
            return await self._search_token_overlap(
                user_id=user_id,
                namespace=ns,
                query=cleaned,
                limit=safe_limit,
            )
        finally:
            agent_metrics.record_memory_query_duration(time.perf_counter() - started)

    async def forget(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Delete one memory entry scoped by user_id + namespace + key."""
        user_id = resolve_user_id(namespace)
        ns = encode_namespace(namespace)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                delete(MemoryEntryORM).where(
                    MemoryEntryORM.user_id == user_id,
                    MemoryEntryORM.namespace == ns,
                    MemoryEntryORM.entry_key == key,
                )
            )
            await session.commit()
            return bool(getattr(result, "rowcount", 0))

    async def bump_access(self, *, namespace: tuple[str, ...], key: str) -> int:
        """Increment access_frequency; return new count (0 if missing)."""
        user_id = resolve_user_id(namespace)
        ns = encode_namespace(namespace)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            stmt = (
                update(MemoryEntryORM)
                .where(
                    MemoryEntryORM.user_id == user_id,
                    MemoryEntryORM.namespace == ns,
                    MemoryEntryORM.entry_key == key,
                )
                .values(
                    access_frequency=MemoryEntryORM.access_frequency + 1,
                    last_accessed=datetime.now(UTC),
                )
                .returning(MemoryEntryORM.access_frequency)
            )
            result = await session.execute(stmt)
            await session.commit()
            count = result.scalar_one_or_none()
            return int(count or 0)

    async def list_promotion_candidates(
        self,
        *,
        user_id: str,
        min_access_frequency: int,
        min_importance: float,
        limit: int = 32,
    ) -> list[PromotionCandidate]:
        """Rows for one RLS user_id not yet promoted that meet hard floors."""
        uid = user_id.strip()
        if not uid:
            return []
        safe_limit = max(1, min(limit, 128))
        async with self._session_factory() as session:
            await set_rls_user_scope(session, uid)
            result = await session.execute(
                select(MemoryEntryORM)
                .where(
                    MemoryEntryORM.user_id == uid,
                    MemoryEntryORM.promoted_at.is_(None),
                    MemoryEntryORM.access_frequency >= min_access_frequency,
                    MemoryEntryORM.importance >= min_importance,
                )
                .order_by(MemoryEntryORM.access_frequency.desc(), MemoryEntryORM.importance.desc())
                .limit(safe_limit)
            )
            rows = list(result.scalars().all())
        candidates: list[PromotionCandidate] = []
        for row in rows:
            text = str(row.value.get("text", "")).strip() if isinstance(row.value, dict) else ""
            if not text:
                text = (row.search_text or "").strip()[:2000]
            if not text:
                continue
            confidence = _value_confidence(row.value if isinstance(row.value, dict) else {})
            candidates.append(
                PromotionCandidate(
                    namespace=decode_namespace(row.namespace),
                    entry_key=row.entry_key,
                    text=text[:2000],
                    kind=str(row.memory_type or "fact")[:32],
                    importance=float(row.importance or 0.0),
                    access_frequency=int(row.access_frequency or 0),
                    user_id=row.user_id,
                    confidence=confidence,
                    last_accessed=row.last_accessed,
                    promoted_at=row.promoted_at,
                )
            )
        return candidates

    async def mark_promoted(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Stamp promoted_at; returns True when a row was updated."""
        user_id = resolve_user_id(namespace)
        ns = encode_namespace(namespace)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            stmt = (
                update(MemoryEntryORM)
                .where(
                    MemoryEntryORM.user_id == user_id,
                    MemoryEntryORM.namespace == ns,
                    MemoryEntryORM.entry_key == key,
                    MemoryEntryORM.promoted_at.is_(None),
                )
                .values(promoted_at=datetime.now(UTC))
            )
            result = await session.execute(stmt)
            await session.commit()
            return bool(getattr(result, "rowcount", 0))

    async def _search_fts(
        self,
        *,
        user_id: str,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[tuple[str, float, dict[str, object]]]:
        ts_vector = func.to_tsvector("simple", MemoryEntryORM.search_text)
        ts_query = func.plainto_tsquery("simple", query)
        rank = cast(func.ts_rank_cd(ts_vector, ts_query), Float)
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(MemoryEntryORM, rank.label("rank"))
                .where(
                    MemoryEntryORM.user_id == user_id,
                    MemoryEntryORM.namespace == namespace,
                    ts_vector.op("@@")(ts_query),
                )
                .order_by(rank.desc(), MemoryEntryORM.importance.desc())
                .limit(limit)
            )
            rows = result.all()
        return [
            (
                row.entry_key,
                float(score or 0.0),
                _payload_from_row(row, float(score or 0.0)),
            )
            for row, score in rows
        ]

    async def _search_vector(
        self,
        *,
        user_id: str,
        namespace: str,
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
        assert_vector_dim(schema="memory", vector_len=len(query_vec))
        distance = MemoryEntryORM.embedding.cosine_distance(query_vec)
        similarity = (1.0 - distance).label("similarity")
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            result = await session.execute(
                select(MemoryEntryORM, similarity)
                .where(
                    MemoryEntryORM.user_id == user_id,
                    MemoryEntryORM.namespace == namespace,
                    MemoryEntryORM.embedding.is_not(None),
                )
                .order_by(distance.asc(), MemoryEntryORM.importance.desc())
                .limit(limit)
            )
            rows = result.all()
        return [
            (
                row.entry_key,
                max(0.0, float(score or 0.0)),
                _payload_from_row(row, max(0.0, float(score or 0.0))),
            )
            for row, score in rows
        ]

    async def _search_token_overlap(
        self,
        *,
        user_id: str,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[dict[str, object]]:
        tokens = {t for t in re.findall(r"[a-zA-Zа-яА-Я0-9_]{2,}", query.lower())}
        async with self._session_factory() as session:
            await set_rls_user_scope(session, user_id)
            filters = [
                MemoryEntryORM.user_id == user_id,
                MemoryEntryORM.namespace == namespace,
            ]
            if tokens:
                filters.append(or_(*[MemoryEntryORM.search_text.ilike(f"%{token}%") for token in list(tokens)[:8]]))
            result = await session.execute(select(MemoryEntryORM).where(*filters).limit(200))
            rows = list(result.scalars().all())
        scored: list[tuple[float, dict[str, object]]] = []
        for row in rows:
            blob = row.search_text.lower()
            overlap = float(sum(1 for token in tokens if token in blob)) if tokens else 1.0
            confidence = _value_confidence(row.value)
            score = overlap * (0.5 + 0.5 * confidence)
            if score > 0:
                scored.append((score, _payload_from_row(row, score)))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item for _, item in scored[:limit]]


def _search_blob(value: dict[str, object]) -> str:
    parts: list[str] = []
    for key, item in value.items():
        parts.append(str(key))
        parts.append(str(item))
    return " ".join(parts)


def _value_confidence(value: dict[str, Any]) -> float:
    return max(0.0, min(1.0, coerce_float(value.get("confidence", 0.0))))


def _payload_from_row(row: MemoryEntryORM, score: float) -> dict[str, object]:
    payload = mask_memory_value(dict(row.value), contains_pii=row.contains_pii)
    return _with_score(payload, score, entry_key=row.entry_key)


def _with_score(value: dict[str, object], score: float, *, entry_key: str = "") -> dict[str, object]:
    enriched = dict(value)
    enriched["_score"] = round(score, 4)
    key = entry_key or str(value.get("_entry_key", "")).strip()
    if key:
        enriched["_entry_key"] = key
    return enriched
