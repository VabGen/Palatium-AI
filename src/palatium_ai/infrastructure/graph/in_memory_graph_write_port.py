# src/palatium_ai/infrastructure/graph/in_memory_graph_write_port.py

"""In-memory bi-temporal GraphWritePort (tests / stub promote path)."""

from __future__ import annotations

import hashlib

from dataclasses import dataclass
from datetime import UTC, datetime

from palatium_ai.domain.graph.temporal import is_fact_active_as_of
from palatium_ai.domain.graph.write_port import GraphFactRecord, GraphFactUpsert
from palatium_ai.domain.memory.hebbian import bump_hebbian_weight
from palatium_ai.domain.policies.graph_fact import GraphFactPolicy


@dataclass
class _StoredFact:
    node_id: str
    user_id: str
    entry_key: str
    text: str
    kind: str
    importance: float
    confidence: float
    version: int
    source_type: str
    contains_pii: bool
    valid_at: datetime
    created_at: datetime
    invalid_at: datetime | None = None
    expired_at: datetime | None = None
    superseded_by: str | None = None
    hebbian_weight: float = 0.0


class InMemoryGraphWritePort:
    """Stores versioned MemoryFact rows with supersede / expire (dev/tests)."""

    def __init__(self) -> None:
        self._by_node: dict[str, _StoredFact] = {}
        self._index: dict[tuple[str, str], list[str]] = {}
        # Compat for older tests that inspect ``.facts``.
        self.facts: dict[str, GraphFactUpsert] = {}

    async def upsert_fact(self, command: GraphFactUpsert) -> str:
        now = datetime.now(UTC)
        key = (command.user_id, command.entry_key)
        active = self._active(key, as_of=now)
        action = GraphFactPolicy.decide_write(
            existing_text=active.text if active else None,
            new_text=command.text,
            contains_pii=command.contains_pii or (active.contains_pii if active else False),
        )
        if action == "blocked_pii":
            return ""
        if action == "refresh" and active is not None:
            active.importance = float(command.importance)
            active.confidence = float(command.confidence)
            self.facts[active.node_id] = command
            return active.node_id

        version = 1 if active is None else active.version + 1
        node_id = _stable_node_id(command.user_id, command.entry_key, version)
        valid_at = command.valid_at or now
        if valid_at.tzinfo is None:
            valid_at = valid_at.replace(tzinfo=UTC)
        stored = _StoredFact(
            node_id=node_id,
            user_id=command.user_id,
            entry_key=command.entry_key,
            text=command.text,
            kind=command.kind,
            importance=float(command.importance),
            confidence=float(command.confidence),
            version=version,
            source_type=command.source_type,
            contains_pii=command.contains_pii,
            valid_at=valid_at,
            created_at=now,
        )
        if action == "supersede" and active is not None:
            active.invalid_at = now
            active.superseded_by = node_id
            active.hebbian_weight = bump_hebbian_weight(active.hebbian_weight)
        self._by_node[node_id] = stored
        self._index.setdefault(key, []).append(node_id)
        self.facts[node_id] = command
        return node_id

    async def bump_hebbian_on_entry(self, *, user_id: str, entry_key: str) -> float:
        """Opt-in M8: reinforce Hebbian weight on the active fact for this entry."""
        now = datetime.now(UTC)
        active = self._active((user_id.strip(), entry_key.strip()), as_of=now)
        if active is None:
            return 0.0
        active.hebbian_weight = bump_hebbian_weight(active.hebbian_weight)
        return active.hebbian_weight

    async def expire_fact(self, *, user_id: str, entry_key: str) -> bool:
        now = datetime.now(UTC)
        key = (user_id.strip(), entry_key.strip())
        acted = False
        for node_id in self._index.get(key, []):
            row = self._by_node[node_id]
            if row.expired_at is None:
                row.expired_at = now
                acted = True
        return acted

    def get_active_fact(
        self,
        *,
        user_id: str,
        entry_key: str,
        as_of: datetime | None = None,
    ) -> GraphFactRecord | None:
        """Test helper: current active fact at as_of."""
        moment = as_of or datetime.now(UTC)
        row = self._active((user_id, entry_key), as_of=moment)
        return _to_record(row) if row is not None else None

    def list_facts_as_of(self, *, user_id: str, as_of: datetime) -> list[GraphFactRecord]:
        """Temporal query surface for unit tests."""
        out: list[GraphFactRecord] = []
        for row in self._by_node.values():
            if row.user_id != user_id:
                continue
            if is_fact_active_as_of(
                valid_at=row.valid_at,
                invalid_at=row.invalid_at,
                expired_at=row.expired_at,
                as_of=as_of,
            ):
                out.append(_to_record(row))
        return out

    def _active(self, key: tuple[str, str], *, as_of: datetime) -> _StoredFact | None:
        for node_id in reversed(self._index.get(key, [])):
            row = self._by_node[node_id]
            if is_fact_active_as_of(
                valid_at=row.valid_at,
                invalid_at=row.invalid_at,
                expired_at=row.expired_at,
                as_of=as_of,
            ):
                return row
        return None


def _to_record(row: _StoredFact) -> GraphFactRecord:
    return GraphFactRecord(
        node_id=row.node_id,
        user_id=row.user_id,
        entry_key=row.entry_key,
        text=row.text,
        kind=row.kind,
        importance=row.importance,
        confidence=row.confidence,
        version=row.version,
        source_type=row.source_type,
        contains_pii=row.contains_pii,
        valid_at=row.valid_at,
        created_at=row.created_at,
        invalid_at=row.invalid_at,
        expired_at=row.expired_at,
        superseded_by=row.superseded_by,
    )


def _stable_node_id(user_id: str, entry_key: str, version: int) -> str:
    return hashlib.sha256(f"{user_id}:{entry_key}:v{version}".encode()).hexdigest()[:24]
