# src/palatium_ai/infrastructure/memory/mem0_adapter.py

"""Mem0 Platform v3 adapter implementing MemoryPort (ADD-only vendor store).

Maps palatium namespaces → Mem0 entity filters:
  ("user", uid)              → user_id
  ("org", oid)               → agent_id = org:{oid}
  ("chat", "thread", tid)    → run_id

Uses REST (/v3/memories/add|search) via httpx — no hard mem0ai SDK dependency.
"""

from __future__ import annotations

from typing import Protocol

import httpx

from palatium_ai.core.logging import get_logger
from palatium_ai.core.types.coerce import coerce_float

logger = get_logger(__name__)


class Mem0Transport(Protocol):
    """Minimal async transport for Mem0 Platform (injectable in tests)."""

    async def add_memory(
        self,
        *,
        text: str,
        scope: dict[str, str],
        metadata: dict[str, object],
    ) -> str | None:
        """Enqueue ADD; returns event/memory id if present."""

    async def search_memories(
        self,
        *,
        query: str,
        scope: dict[str, str],
        limit: int,
    ) -> list[dict[str, object]]:
        """Search within entity scope; returns normalized hit dicts."""

    async def aclose(self) -> None:
        """Close underlying HTTP resources."""


def namespace_to_scope(namespace: tuple[str, ...]) -> dict[str, str]:
    """Map palatium namespace tuple to Mem0 entity filter fields."""
    if len(namespace) >= 2 and namespace[0] == "user" and namespace[1].strip():
        return {"user_id": namespace[1].strip()}
    if len(namespace) >= 2 and namespace[0] == "org" and namespace[1].strip():
        return {"agent_id": f"org:{namespace[1].strip()}"}
    if len(namespace) >= 3 and namespace[0] == "chat" and namespace[1] == "thread" and namespace[2].strip():
        return {"run_id": namespace[2].strip()}
    joined = "/".join(part for part in namespace if part.strip()) or "default"
    return {"run_id": joined}


class Mem0HttpTransport:
    """httpx client for Mem0 Platform v3 add/search."""

    def __init__(
        self,
        *,
        api_key: str,
        host: str = "https://api.mem0.ai",
        timeout_seconds: float = 30.0,
    ) -> None:
        if not api_key.strip():
            raise ValueError("MEM0_API_KEY is required for Mem0MemoryPort")
        self._host = host.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._host,
            headers={
                "Authorization": f"Token {api_key.strip()}",
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
        )

    async def add_memory(
        self,
        *,
        text: str,
        scope: dict[str, str],
        metadata: dict[str, object],
    ) -> str | None:
        """POST /v3/memories/add/ (async ADD-only pipeline)."""
        body: dict[str, object] = {
            "messages": [{"role": "user", "content": text}],
            "metadata": metadata,
            **scope,
        }
        response = await self._client.post("/v3/memories/add/", json=body)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            for key in ("event_id", "id", "memory_id"):
                if payload.get(key):
                    return str(payload[key])
            results = payload.get("results")
            if isinstance(results, list) and results and isinstance(results[0], dict):
                first = results[0]
                for key in ("id", "event_id", "memory_id"):
                    if first.get(key):
                        return str(first[key])
        return None

    async def search_memories(
        self,
        *,
        query: str,
        scope: dict[str, str],
        limit: int,
    ) -> list[dict[str, object]]:
        """POST /v3/memories/search/ with entity filters."""
        body: dict[str, object] = {
            "query": query,
            "filters": scope,
            "top_k": max(1, min(limit, 32)),
        }
        response = await self._client.post("/v3/memories/search/", json=body)
        response.raise_for_status()
        payload = response.json()
        raw_results: list[object]
        if isinstance(payload, dict):
            maybe = payload.get("results", [])
            raw_results = maybe if isinstance(maybe, list) else []
        elif isinstance(payload, list):
            raw_results = payload
        else:
            raw_results = []

        hits: list[dict[str, object]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            text = str(item.get("memory") or item.get("text") or "").strip()
            if not text:
                continue
            meta_raw = item.get("metadata")
            meta: dict[str, object] = meta_raw if isinstance(meta_raw, dict) else {}
            score = coerce_float(item.get("score", 0.0) or 0.0)
            confidence = max(
                0.0,
                min(1.0, coerce_float(meta.get("confidence", item.get("confidence", 0.85)), 0.85)),
            )
            hits.append(
                {
                    "text": text,
                    "kind": str(meta.get("kind", "fact"))[:32],
                    "confidence": confidence,
                    "_score": round(score, 4),
                    "_mem0_id": str(item.get("id", "")),
                    "palatium_key": str(meta.get("palatium_key", "")),
                }
            )
        return hits

    async def aclose(self) -> None:
        """Close HTTP client."""
        await self._client.aclose()


class Mem0MemoryPort:
    """MemoryPort backed by Mem0 Platform (vendor adapter)."""

    def __init__(self, transport: Mem0Transport) -> None:
        self._transport = transport

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        """ADD-only upsert via Mem0 (platform extracts/stores asynchronously)."""
        text = str(value.get("text", "")).strip()
        if not text:
            return
        scope = namespace_to_scope(namespace)
        metadata: dict[str, object] = {
            "palatium_key": key,
            "palatium_namespace": "/".join(namespace),
            "kind": str(value.get("kind", "fact"))[:32],
            "confidence": coerce_float(value.get("confidence", 0.8) or 0.8, 0.8),
        }
        for extra in ("source_task_id", "thread_id", "user_id", "org_id"):
            if value.get(extra) is not None:
                metadata[extra] = value[extra]
        event_id = await self._transport.add_memory(text=text, scope=scope, metadata=metadata)
        logger.debug(
            "mem0.put",
            namespace="/".join(namespace),
            key=key,
            event_id=event_id or "",
        )

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        """Best-effort get by palatium_key via scoped search."""
        # Prefer key tokens so lexical backends can match metadata/key slug.
        query = key.replace("-", " ").replace(":", " ").strip() or key
        hits = await self._transport.search_memories(
            query=query,
            scope=namespace_to_scope(namespace),
            limit=16,
        )
        for hit in hits:
            if str(hit.get("palatium_key", "")) == key:
                return {
                    "text": hit["text"],
                    "kind": hit.get("kind", "fact"),
                    "confidence": hit.get("confidence", 0.0),
                }
        return None

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        """Scoped semantic/hybrid search."""
        cleaned = query.strip()
        if not cleaned:
            return []
        return await self._transport.search_memories(
            query=cleaned,
            scope=namespace_to_scope(namespace),
            limit=limit,
        )

    async def aclose(self) -> None:
        """Close transport resources."""
        await self._transport.aclose()
