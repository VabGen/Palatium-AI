# src/palatium_ai/infrastructure/graph/neo4j_graph_write_port.py

"""Neo4j GraphWritePort — bi-temporal MemoryFact promote (060 / Wave M5)."""

from __future__ import annotations

import hashlib

from datetime import UTC, datetime
from typing import Protocol

from palatium_ai.domain.graph.temporal import EXPIRED_AT_SENTINEL
from palatium_ai.domain.graph.write_port import GraphFactRecord, GraphFactUpsert
from palatium_ai.domain.memory.hebbian import bump_hebbian_weight
from palatium_ai.domain.policies.graph_fact import GraphFactPolicy

# Fixed templates — never f-string user text into Cypher (070 / 020).
# Active = visible *now*: not invalidated yet and not system-expired. ``invalid_at`` is
# compared instead of tested for NULL because a scheduled (future-dated) supersede must
# not make the still-current fact invisible to the next write — that would CREATE a
# second version for the same key instead of superseding.
_FIND_ACTIVE_CYPHER = """
MATCH (f:MemoryFact {user_id: $user_id, entry_key: $entry_key})
WHERE (f.invalid_at IS NULL OR f.invalid_at > datetime())
  AND (f.expired_at IS NULL OR f.expired_at > datetime())
RETURN f.text AS text, f.node_id AS node_id, f.version AS version,
       coalesce(f.contains_pii, false) AS contains_pii,
       coalesce(f.hebbian_weight, 0.0) AS hebbian_weight
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

# ``MERGE`` on the deterministic ``node_id`` instead of ``CREATE`` (M5 audit F6): a
# re-run of the same version (retry, or two promoters that both passed the old
# read-then-write check) must converge on one node, not add a twin active fact. The
# uniqueness constraint in ``neo4j_schema`` is the hard guarantee; MERGE makes the
# ordinary repeat a no-op. ``ON MATCH`` deliberately does not touch ``valid_at`` /
# ``created_at`` / ``expired_at``: the match means "this version already exists", so
# rewriting its lifecycle would erase history (or revive a forgotten fact).
_NODE_SET_ON_CREATE = """
  f.user_id = $user_id,
  f.entry_key = $entry_key,
  f.text = $text,
  f.kind = $kind,
  f.importance = $importance,
  f.confidence = $confidence,
  f.version = $version,
  f.thread_id = $thread_id,
  f.source_namespace = $source_namespace,
  f.source_type = $source_type,
  f.contains_pii = $contains_pii,
  f.valid_at = datetime($valid_at),
  f.created_at = datetime(),
  f.invalid_at = null,
  f.expired_at = datetime($sentinel)
""".rstrip()

_NODE_SET_ON_MATCH = """
  f.text = $text,
  f.kind = $kind,
  f.importance = $importance,
  f.confidence = $confidence,
  f.updated_at = datetime()
""".rstrip()

_CREATE_CYPHER = f"""
MERGE (f:MemoryFact {{node_id: $node_id}})
ON CREATE SET {_NODE_SET_ON_CREATE}
ON MATCH SET {_NODE_SET_ON_MATCH}
RETURN f.node_id AS node_id
""".strip()

_SUPERSEDE_CYPHER = f"""
MATCH (old:MemoryFact {{node_id: $old_node_id}})
SET old.invalid_at = datetime($valid_at), old.updated_at = datetime()
MERGE (f:MemoryFact {{node_id: $node_id}})
ON CREATE SET {_NODE_SET_ON_CREATE}
ON MATCH SET {_NODE_SET_ON_MATCH}
MERGE (f)-[:SUPERSEDES]->(old)
SET old.superseded_by = $node_id
RETURN f.node_id AS node_id
""".strip()

# Highest version across *all* nodes of the key, including superseded and expired ones.
# Create path only: after a forget the active fact is gone, and restarting at version 1
# would collide with the expired node's deterministic ``node_id`` (MERGE would then
# "match" a forgotten fact and update its text while it stays expired — invisible).
_MAX_VERSION_CYPHER = """
MATCH (f:MemoryFact {user_id: $user_id, entry_key: $entry_key})
RETURN coalesce(max(f.version), 0) AS max_version
""".strip()

_EXPIRE_CYPHER = """
MATCH (f:MemoryFact {user_id: $user_id, entry_key: $entry_key})
WHERE f.expired_at IS NULL OR f.expired_at > datetime()
SET f.expired_at = datetime(), f.updated_at = datetime()
RETURN count(f) AS n
""".strip()

_SET_HEBBIAN_CYPHER = """
MATCH (f:MemoryFact {node_id: $node_id})
SET f.hebbian_weight = $hebbian_weight,
    f.updated_at = datetime()
RETURN f.hebbian_weight AS hebbian_weight
""".strip()

# Bi-temporal active Select for hot-path fusion (SB3); binds $as_of / $user_id / $limit.
#
# Thread scoping is TWO fixed shapes, never one query with an optional predicate.
# ``$thread_id = '' OR f.thread_id = $thread_id OR f.thread_id IS NULL OR f.thread_id = ''``
# is a disjunction over an indexed property: the planner cannot use
# ``memory_fact_user_thread`` for it and falls back to scanning every ``MemoryFact``
# (observed ``t_first`` ≈ 51 s on the recall hot path). With a thread bound the
# composite index is usable; without one the predicate is simply absent, so the
# shape stays a single index seek on ``user_id`` (080: no unbounded scan).
_ACTIVE_FACT_FILTER = """
  AND (f.valid_at IS NULL OR f.valid_at <= datetime($as_of))
  AND (f.invalid_at IS NULL OR f.invalid_at > datetime($as_of))
  AND (f.expired_at IS NULL OR f.expired_at > datetime($as_of))
""".rstrip()

_ACTIVE_FACT_RETURN = """
RETURN f.node_id AS node_id, f.user_id AS user_id, f.entry_key AS entry_key,
       f.text AS text, f.kind AS kind, coalesce(f.importance, 0.0) AS importance,
       coalesce(f.confidence, 0.0) AS confidence, coalesce(f.version, 1) AS version,
       coalesce(f.source_type, 'promote') AS source_type,
       coalesce(f.contains_pii, false) AS contains_pii
ORDER BY coalesce(f.importance, 0.0) DESC, coalesce(f.confidence, 0.0) DESC
LIMIT $limit
""".rstrip()

_LIST_ACTIVE_CYPHER = f"""
MATCH (f:MemoryFact)
WHERE f.user_id = $user_id{_ACTIVE_FACT_FILTER}{_ACTIVE_FACT_RETURN}
""".strip()

# Empty ``thread_id`` keeps the previous semantics (all user facts active at ``as_of``);
# a bound thread adds equality on the indexed property instead of a disjunction.
_LIST_ACTIVE_THREAD_CYPHER = f"""
MATCH (f:MemoryFact)
WHERE f.user_id = $user_id
  AND f.thread_id = $thread_id{_ACTIVE_FACT_FILTER}{_ACTIVE_FACT_RETURN}
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

        if action == "create":
            # Not always 1: a forgotten key keeps its historical versions, and reusing
            # version 1 would MERGE into the expired node instead of recording a new fact.
            rows = await self._transport.run_write(
                cypher=_MAX_VERSION_CYPHER,
                params={"user_id": command.user_id, "entry_key": command.entry_key},
            )
            highest = _row_int(rows[0].get("max_version"), default=0) if rows else 0
            version = max(1, highest + 1)
        else:
            version = max(1, old_version) + 1
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
        """Reinforce the active fact's Hebbian weight (M8 curve, same as in-memory port).

        Read → compute in the domain helper → write. Keeping the formula in one place
        (``domain.memory.hebbian``) avoids a second copy in Cypher that would drift.
        Concurrent bumps of the same entry are last-write-wins: the weight is a
        heuristic signal used only by the promote batch, not a durable fact.
        """
        uid = user_id.strip()
        key = entry_key.strip()
        if not uid or not key:
            return 0.0
        rows = await self._transport.run_write(
            cypher=_FIND_ACTIVE_CYPHER,
            params={"user_id": uid, "entry_key": key},
        )
        if not rows:
            return 0.0
        node_id = str(rows[0].get("node_id", "") or "").strip()
        if not node_id:
            return 0.0
        weight = bump_hebbian_weight(_row_float(rows[0].get("hebbian_weight"), default=0.0))
        updated = await self._transport.run_write(
            cypher=_SET_HEBBIAN_CYPHER,
            params={"node_id": node_id, "hebbian_weight": weight},
        )
        if not updated:
            return 0.0
        stored = _row_float(updated[0].get("hebbian_weight"), default=weight)
        return max(0.0, min(1.0, stored))

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
        scope_thread = (thread_id or "").strip()
        params: dict[str, object] = {
            "user_id": user_id.strip(),
            "as_of": as_of_iso,
            "limit": safe_limit,
        }
        cypher = _LIST_ACTIVE_CYPHER
        if scope_thread:
            cypher = _LIST_ACTIVE_THREAD_CYPHER
            params["thread_id"] = scope_thread
        rows = await self._transport.run_write(cypher=cypher, params=params)
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
