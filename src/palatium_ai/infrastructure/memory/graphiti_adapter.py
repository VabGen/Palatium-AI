# src/palatium_ai/infrastructure/memory/graphiti_adapter.py

"""Graphiti (Zep) adapter implementing MemoryPort — bi-temporal graph memory.

Maps palatium namespaces → Graphiti ``group_id``:
  ("user", uid)           → user:{uid}
  ("org", oid)            → org:{oid}
  ("chat", "thread", tid) → thread:{tid}

Real Neo4j transport is optional (``graphiti-core``). Tests inject a fake transport.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from palatium_ai.core.logging import get_logger
from palatium_ai.core.types.coerce import coerce_float

logger = get_logger(__name__)


class GraphitiTransport(Protocol):
    """Minimal async Graphiti surface (injectable in tests)."""

    async def add_episode(
        self,
        *,
        name: str,
        body: str,
        group_id: str,
        reference_time: datetime,
        source_description: str,
    ) -> str | None:
        """Ingest one episode; returns episode/node id if available."""

    async def search(
        self,
        *,
        query: str,
        group_id: str,
        limit: int,
    ) -> list[dict[str, object]]:
        """Hybrid search; returns normalized hit dicts with text/score."""

    async def aclose(self) -> None:
        """Close driver / SDK resources."""


def namespace_to_group_id(namespace: tuple[str, ...]) -> str:
    """Map palatium namespace tuple to Graphiti group_id."""
    if len(namespace) >= 2 and namespace[0] == "user" and namespace[1].strip():
        return f"user:{namespace[1].strip()}"
    if len(namespace) >= 2 and namespace[0] == "org" and namespace[1].strip():
        return f"org:{namespace[1].strip()}"
    if len(namespace) >= 3 and namespace[0] == "chat" and namespace[1] == "thread" and namespace[2].strip():
        return f"thread:{namespace[2].strip()}"
    joined = "/".join(part for part in namespace if part.strip()) or "default"
    return f"ns:{joined}"


class GraphitiSdkTransport:
    """Lazy ``graphiti_core.Graphiti`` wrapper (optional dependency)."""

    def __init__(
        self,
        *,
        uri: str,
        user: str,
        password: str,
    ) -> None:
        try:
            from graphiti_core import Graphiti
        except ImportError as exc:
            raise ImportError(
                "MEMORY_BACKEND=graphiti requires graphiti-core (poetry add graphiti-core) and a reachable Neo4j"
            ) from exc
        if not uri.strip() or not password:
            raise ValueError("GRAPHITI_NEO4J_URI and GRAPHITI_NEO4J_PASSWORD are required")
        self._graphiti = Graphiti(uri.strip(), user.strip() or "neo4j", password)

    async def add_episode(
        self,
        *,
        name: str,
        body: str,
        group_id: str,
        reference_time: datetime,
        source_description: str,
    ) -> str | None:
        """Add text episode into the temporal graph."""
        from graphiti_core.nodes import EpisodeType

        result = await self._graphiti.add_episode(
            name=name,
            episode_body=body,
            source=EpisodeType.text,
            source_description=source_description,
            reference_time=reference_time,
            group_id=group_id,
        )
        if result is None:
            return None
        for attr in ("uuid", "id", "episode_uuid"):
            value = getattr(result, attr, None)
            if value:
                return str(value)
        return str(result) if result else None

    async def search(
        self,
        *,
        query: str,
        group_id: str,
        limit: int,
    ) -> list[dict[str, object]]:
        """Search edges/facts within a group."""
        edges = await self._graphiti.search(
            query,
            group_ids=[group_id],
            num_results=max(1, min(limit, 32)),
        )
        hits: list[dict[str, object]] = []
        for edge in edges or []:
            fact = str(getattr(edge, "fact", "") or "").strip()
            if not fact:
                continue
            score = getattr(edge, "score", None)
            score_f = coerce_float(score)
            hits.append(
                {
                    "text": fact,
                    "kind": "entity",
                    "confidence": 0.85,
                    "_score": round(score_f, 4),
                    "_graphiti_uuid": str(getattr(edge, "uuid", "")),
                }
            )
        return hits

    async def aclose(self) -> None:
        """Close Graphiti / Neo4j driver."""
        closer = getattr(self._graphiti, "close", None)
        if closer is not None:
            await closer()


class GraphitiMemoryPort:
    """MemoryPort backed by Graphiti temporal knowledge graph."""

    def __init__(self, transport: GraphitiTransport) -> None:
        self._transport = transport

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        """Ingest fact as a Graphiti episode (ADD / temporal update handled by Graphiti)."""
        text = str(value.get("text", "")).strip()
        if not text:
            return
        group_id = namespace_to_group_id(namespace)
        kind = str(value.get("kind", "fact"))[:32]
        body = f"[{kind}] {text}"
        episode_id = await self._transport.add_episode(
            name=f"palatium:{key}"[:128],
            body=body,
            group_id=group_id,
            reference_time=datetime.now(UTC),
            source_description="palatium-ai MemoryKeeper",
        )
        logger.debug(
            "graphiti.put",
            namespace="/".join(namespace),
            key=key,
            group_id=group_id,
            episode_id=episode_id or "",
        )

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        """Best-effort get: search by key tokens within group."""
        query = key.replace("-", " ").replace(":", " ").strip() or key
        hits = await self.search(namespace=namespace, query=query, limit=16)
        for hit in hits:
            if key.replace("-", " ") in str(hit.get("text", "")).lower().replace("-", " "):
                return {
                    "text": hit["text"],
                    "kind": hit.get("kind", "entity"),
                    "confidence": hit.get("confidence", 0.0),
                }
        return hits[0] if hits else None

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Scoped hybrid graph search."""
        cleaned = query.strip()
        if not cleaned:
            return []
        return await self._transport.search(
            query=cleaned,
            group_id=namespace_to_group_id(namespace),
            limit=limit,
        )

    async def forget(self, *, namespace: tuple[str, ...], key: str) -> bool:
        """Graphiti adapter does not support keyed delete yet."""
        _ = namespace, key
        return False

    async def aclose(self) -> None:
        """Close transport resources."""
        await self._transport.aclose()
