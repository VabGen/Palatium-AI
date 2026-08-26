# src/palatium_ai/infrastructure/memory/postgres_memory_port.py

"""Postgres-backed MemoryPort (cross-thread durable store)."""

from __future__ import annotations

import re

from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, cast, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from palatium_ai.core.types.coerce import coerce_float
from palatium_ai.infrastructure.database.models.memory_item import MemoryItemORM

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def encode_namespace(namespace: tuple[str, ...]) -> str:
    """Stable string key for namespace tuple."""
    return "/".join(part.replace("/", "_") for part in namespace)


class PostgresMemoryPort:
    """Implements MemoryPort against palatium_ai.memory_items."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        """Upsert a memory item under namespace/key."""
        ns = encode_namespace(namespace)
        search_text = _search_blob(value)
        async with self._session_factory() as session:
            stmt = (
                insert(MemoryItemORM)
                .values(
                    namespace=ns,
                    key=key,
                    value=value,
                    search_text=search_text,
                )
                .on_conflict_do_update(
                    constraint="uq_memory_items_namespace_key",
                    set_={
                        "value": value,
                        "search_text": search_text,
                    },
                )
            )
            await session.execute(stmt)
            await session.commit()

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        """Fetch one item or None."""
        ns = encode_namespace(namespace)
        async with self._session_factory() as session:
            result = await session.execute(
                select(MemoryItemORM).where(
                    MemoryItemORM.namespace == ns,
                    MemoryItemORM.key == key,
                )
            )
            row = result.scalar_one_or_none()
            if row is None:
                return None
            return dict(row.value)

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Hybrid retrieve: Postgres FTS (simple) + token-overlap fallback."""
        ns = encode_namespace(namespace)
        safe_limit = max(1, min(limit, 32))
        cleaned = query.strip()
        if not cleaned:
            return []

        fts_hits = await self._search_fts(namespace=ns, query=cleaned, limit=safe_limit)
        if fts_hits:
            return fts_hits
        return await self._search_token_overlap(namespace=ns, query=cleaned, limit=safe_limit)

    async def _search_fts(
        self,
        *,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[dict[str, object]]:
        ts_vector = func.to_tsvector("simple", MemoryItemORM.search_text)
        ts_query = func.plainto_tsquery("simple", query)
        rank = cast(func.ts_rank(ts_vector, ts_query), Float)
        async with self._session_factory() as session:
            result = await session.execute(
                select(MemoryItemORM, rank.label("rank"))
                .where(MemoryItemORM.namespace == namespace, ts_vector.op("@@")(ts_query))
                .order_by(rank.desc())
                .limit(limit)
            )
            rows = result.all()
        return [_with_score(dict(row.value), float(score or 0.0)) for row, score in rows]

    async def _search_token_overlap(
        self,
        *,
        namespace: str,
        query: str,
        limit: int,
    ) -> list[dict[str, object]]:
        tokens = {t for t in re.findall(r"[a-zA-Zа-яА-Я0-9_]{2,}", query.lower())}
        async with self._session_factory() as session:
            # Prefer ILIKE any token when FTS missed (short/RU stemming edge cases).
            filters = [MemoryItemORM.namespace == namespace]
            if tokens:
                filters.append(or_(*[MemoryItemORM.search_text.ilike(f"%{token}%") for token in list(tokens)[:8]]))
            result = await session.execute(select(MemoryItemORM).where(*filters).limit(200))
            rows = list(result.scalars().all())
        scored: list[tuple[float, dict[str, object]]] = []
        for row in rows:
            blob = row.search_text.lower()
            overlap = float(sum(1 for token in tokens if token in blob)) if tokens else 1.0
            confidence = _value_confidence(row.value)
            score = overlap * (0.5 + 0.5 * confidence)
            if score > 0:
                scored.append((score, _with_score(dict(row.value), score)))
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


def _with_score(value: dict[str, object], score: float) -> dict[str, object]:
    enriched = dict(value)
    enriched["_score"] = round(score, 4)
    return enriched
