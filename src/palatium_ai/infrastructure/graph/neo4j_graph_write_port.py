# src/palatium_ai/infrastructure/graph/neo4j_graph_write_port.py

"""Neo4j GraphWritePort — bi-temporal MemoryFact promote (060 / Wave M5)."""

from __future__ import annotations

import hashlib

from datetime import UTC, datetime
from typing import Protocol

from palatium_ai.domain.graph.temporal import EXPIRED_AT_SENTINEL
from palatium_ai.domain.graph.write_port import GraphFactRecord, GraphFactUpsert
from palatium_ai.domain.policies.graph_fact import GraphFactPolicy

# Fixed templates — never f-string user text into Cypher (070 / 020).
# Active = not invalidated and not yet system-expired (NULL legacy or far-future sentinel).
_FIND_ACTIVE_CYPHER = """
MATCH (f:MemoryFact {user_id: $user_id, entry_key: $entry_key})
WHERE f.invalid_at IS NULL
  AND (f.expired_at IS NULL OR f.expired_at > datetime())
RETURN f.text AS text, f.node_id AS node_id, f.version AS version,
       coalesce(f.contains_pii, false) AS contains_pii
ORDER BY coalesce(f.version, 1) DESC
LIMIT 1
""".strip()

_REFRESH_CYPHER = """
MATCH (f:MemoryFact {node_id: $node_id})
SET f.importance = $importance,
    f.confidence = $confidence,
    f.updated_at = datetime()
RETURN f.node_id AS node_id
""".strip()

_CREATE_CYPHER = """
CREATE (f:MemoryFact {
  node_id: $node_id,
  user_id: $user_id,
  entry_key: $entry_key,
  text: $text,
  kind: $kind,
  importance: $importance,
  confidence: $confidence,
  version: $version,
  thread_id: $thread_id,
  source_namespace: $source_namespace,
  source_type: $source_type,
  contains_pii: $contains_pii,
  valid_at: datetime($valid_at),
  created_at: datetime(),
  invalid_at: null,
  expired_at: datetime($sentinel)
})
RETURN f.node_id AS node_id
""".strip()

_SUPERSEDE_CYPHER = """
MATCH (old:MemoryFact {node_id: $old_node_id})
SET old.invalid_at = datetime(), old.updated_at = datetime()
CREATE (f:MemoryFact {
  node_id: $node_id,
  user_id: $user_id,
  entry_key: $entry_key,
  text: $text,
  kind: $kind,
  importance: $importance,
  confidence: $confidence,
  version: $version,
  thread_id: $thread_id,
  source_namespace: $source_namespace,
  source_type: $source_type,
  contains_pii: $contains_pii,
  valid_at: datetime($valid_at),
  created_at: datetime(),
  invalid_at: null,
  expired_at: datetime($sentinel)
})
CREATE (f)-[:SUPERSEDES]->(old)
SET old.superseded_by = $node_id
RETURN f.node_id AS node_id
""".strip()

_EXPIRE_CYPHER = """
MATCH (f:MemoryFact {user_id: $user_id, entry_key: $entry_key})
WHERE f.expired_at IS NULL OR f.expired_at > datetime()
SET f.expired_at = datetime(), f.updated_at = datetime()
RETURN count(f) AS n
""".strip()

# Bi-temporal active Select for hot-path fusion (SB3); binds $as_of / $user_id / $limit.
_LIST_ACTIVE_CYPHER = """
MATCH (f:MemoryFact)
WHERE f.user_id = $user_id
  AND (f.valid_at IS NULL OR f.valid_at <= datetime($as_of))
  AND (f.invalid_at IS NULL OR f.invalid_at > datetime($as_of))
  AND (f.expired_at IS NULL OR f.expired_at > datetime($as_of))
  AND ($thread_id = '' OR f.thread_id = $thread_id OR f.thread_id IS NULL OR f.thread_id = '')
RETURN f.node_id AS node_id, f.user_id AS user_id, f.entry_key AS entry_key,
       f.text AS text, f.kind AS kind, coalesce(f.importance, 0.0) AS importance,
       coalesce(f.confidence, 0.0) AS confidence, coalesce(f.version, 1) AS version,
       coalesce(f.source_type, 'promote') AS source_type,
       coalesce(f.contains_pii, false) AS contains_pii
ORDER BY coalesce(f.importance, 0.0) DESC, coalesce(f.confidence, 0.0) DESC
LIMIT $limit
""".strip()


def _row_int(value: object, *, default: int) -> int:
    """Coerce Neo4j row cell to int; non-numeric → default."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _row_float(value: object, *, default: float) -> float:
    """Coerce Neo4j row cell to float; non-numeric → default."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


class Neo4jWriteTransport(Protocol):
    """Minimal async write surface (injectable in tests)."""

    async def run_write(
        self,
        *,
        cypher: str,
        params: dict[str, object],
    ) -> list[dict[str, object]]:
        """Execute parameterized write/read Cypher; return result rows."""
        ...

    async def aclose(self) -> None:
        """Close driver / pool resources."""
        ...


class Neo4jGraphWritePort:
    """Upsert long-term MemoryFact with supersede; expire for forget fan-out."""

    def __init__(self, transport: Neo4jWriteTransport) -> None:
        self._transport = transport

    async def upsert_fact(self, command: GraphFactUpsert) -> str:
        find_rows = await self._transport.run_write(
            cypher=_FIND_ACTIVE_CYPHER,
            params={"user_id": command.user_id, "entry_key": command.entry_key},
        )
        existing_text: str | None = None
        old_node_id: str | None = None
        old_version = 0
        existing_pii = False
        if find_rows:
            existing_text = str(find_rows[0].get("text", "") or "") or None
            raw_id = find_rows[0].get("node_id")
            old_node_id = str(raw_id).strip() if raw_id else None
            old_version = _row_int(find_rows[0].get("version"), default=0)
            existing_pii = bool(find_rows[0].get("contains_pii", False))

        action = GraphFactPolicy.decide_write(
            existing_text=existing_text,
            new_text=command.text,
            contains_pii=command.contains_pii or existing_pii,
        )
        if action == "blocked_pii":
            return ""

        valid_at = command.valid_at or datetime.now(UTC)
        if valid_at.tzinfo is None:
            valid_at = valid_at.replace(tzinfo=UTC)
        valid_at_iso = valid_at.astimezone(UTC).isoformat().replace("+00:00", "Z")

        if action == "refresh" and old_node_id:
            rows = await self._transport.run_write(
                cypher=_REFRESH_CYPHER,
                params={
                    "node_id": old_node_id,
                    "importance": float(command.importance),
                    "confidence": float(command.confidence),
                },
            )
            return _row_node_id(rows, fallback=old_node_id)

        version = 1 if action == "create" else max(1, old_version) + 1
        node_id = _stable_node_id(command.user_id, command.entry_key, version)
        base_params: dict[str, object] = {
            "node_id": node_id,
            "user_id": command.user_id,
            "entry_key": command.entry_key,
            "text": command.text,
            "kind": command.kind,
            "importance": float(command.importance),
            "confidence": float(command.confidence),
            "version": version,
            "thread_id": command.thread_id,
            "source_namespace": "/".join(command.source_namespace),
            "source_type": command.source_type,
            "contains_pii": bool(command.contains_pii),
            "valid_at": valid_at_iso,
            "sentinel": EXPIRED_AT_SENTINEL,
        }
        if action == "supersede" and old_node_id:
            rows = await self._transport.run_write(
                cypher=_SUPERSEDE_CYPHER,
                params={**base_params, "old_node_id": old_node_id},
            )
            return _row_node_id(rows, fallback=node_id)

        rows = await self._transport.run_write(cypher=_CREATE_CYPHER, params=base_params)
        return _row_node_id(rows, fallback=node_id)

    async def expire_fact(self, *, user_id: str, entry_key: str) -> bool:
        rows = await self._transport.run_write(
            cypher=_EXPIRE_CYPHER,
            params={"user_id": user_id.strip(), "entry_key": entry_key.strip()},
        )
        if not rows:
            return False
        return _row_int(rows[0].get("n"), default=0) > 0

    async def bump_hebbian_on_entry(self, *, user_id: str, entry_key: str) -> float:
        """Hebbian edge bump is in-memory/eval-gated (M8); Neo4j path is a no-op for now."""
        _ = (user_id, entry_key)
        return 0.0

    async def list_active_facts(
        self,
        *,
        user_id: str,
        limit: int = 8,
        as_of: datetime | None = None,
        thread_id: str | None = None,
    ) -> list[GraphFactRecord]:
        """Budgeted active MemoryFact Select for L4 hot-path fusion (SB3)."""
        moment = as_of or datetime.now(UTC)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=UTC)
        as_of_iso = moment.astimezone(UTC).isoformat().replace("+00:00", "Z")
        safe_limit = max(1, min(int(limit), 32))
        rows = await self._transport.run_write(
            cypher=_LIST_ACTIVE_CYPHER,
            params={
                "user_id": user_id.strip(),
                "as_of": as_of_iso,
                "limit": safe_limit,
                "thread_id": (thread_id or "").strip(),
            },
        )
        out: list[GraphFactRecord] = []
        for row in rows:
            text = str(row.get("text", "") or "").strip()
            node_id = str(row.get("node_id", "") or "").strip()
            entry_key = str(row.get("entry_key", "") or "").strip()
            if not text or not node_id or not entry_key:
                continue
            importance = _row_float(row.get("importance"), default=0.0)
            confidence = _row_float(row.get("confidence"), default=0.0)
            version = _row_int(row.get("version"), default=1)
            out.append(
                GraphFactRecord(
                    node_id=node_id,
                    user_id=str(row.get("user_id", user_id)),
                    entry_key=entry_key,
                    text=text[:2000],
                    kind=str(row.get("kind", "fact") or "fact")[:32],
                    importance=max(0.0, min(1.0, importance)),
                    confidence=max(0.0, min(1.0, confidence)),
                    version=max(1, version),
                    source_type=str(row.get("source_type", "promote") or "promote")[:32],
                    contains_pii=bool(row.get("contains_pii", False)),
                )
            )
        return out

    async def aclose(self) -> None:
        await self._transport.aclose()


def _stable_node_id(user_id: str, entry_key: str, version: int = 1) -> str:
    return hashlib.sha256(f"{user_id}:{entry_key}:v{version}".encode()).hexdigest()[:24]


def _row_node_id(rows: list[dict[str, object]], *, fallback: str) -> str:
    if rows:
        returned = rows[0].get("node_id")
        if isinstance(returned, str) and returned.strip():
            return returned.strip()
    return fallback
