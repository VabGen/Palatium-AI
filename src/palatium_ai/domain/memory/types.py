# src/palatium_ai/domain/memory/types.py

"""Типы записей эпизодической памяти (060) — единственный источник."""

from __future__ import annotations

from typing import Literal

MemoryType = Literal["preference", "fact", "incident", "episode"]

#: Value marker for a write a human explicitly approved («запомни …», 020/060).
#: Hot-path recall treats these as deliberate durable memory: an approved fact may
#: cross threads, while facts *inferred* by extract stay thread-scoped (P0-B bleed).
MEMORY_EXPLICIT_WRITE_KEY = "explicit_write"

#: Provenance axis (ADR 0008 / CMD1). Stored inside the medium value JSON.
MEMORY_ORIGIN_KEY = "origin"
MemoryOrigin = Literal["user_hitl", "extract", "compact", "system", "legacy"]
_VALID_ORIGINS: frozenset[str] = frozenset({"user_hitl", "extract", "compact", "system", "legacy"})

#: Staged trust (ADR 0008). ``inferred`` is demoted on recall; ``quarantined`` is excluded.
MEMORY_TRUST_KEY = "trust"
MemoryTrust = Literal["verified", "inferred", "quarantined"]
_VALID_TRUSTS: frozenset[str] = frozenset({"verified", "inferred", "quarantined"})


def coerce_memory_origin(raw: object) -> MemoryOrigin | None:
    """Return a closed origin or None when absent/garbage."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value in _VALID_ORIGINS:
        return value  # type: ignore[return-value]  # membership не сужает str→Literal (017)
    return None


def coerce_memory_trust(raw: object) -> MemoryTrust | None:
    """Return a closed trust or None when absent/garbage."""
    if not isinstance(raw, str):
        return None
    value = raw.strip().lower()
    if value in _VALID_TRUSTS:
        return value  # type: ignore[return-value]  # membership не сужает str→Literal (017)
    return None


def resolve_memory_origin(item: dict[str, object]) -> MemoryOrigin:
    """Resolve origin for recall/promote; missing → ``legacy`` (ADR 0008)."""
    explicit = _is_truthy(item.get(MEMORY_EXPLICIT_WRITE_KEY))
    stamped = coerce_memory_origin(item.get(MEMORY_ORIGIN_KEY))
    if stamped is not None:
        return stamped
    if explicit:
        return "user_hitl"
    if str(item.get("source_task_id", "")).strip():
        return "extract"
    return "legacy"


def resolve_memory_trust(item: dict[str, object]) -> MemoryTrust:
    """Resolve trust; legacy/explicit rules per ADR 0008."""
    stamped = coerce_memory_trust(item.get(MEMORY_TRUST_KEY))
    if stamped is not None:
        return stamped
    if _is_truthy(item.get(MEMORY_EXPLICIT_WRITE_KEY)):
        return "verified"
    return "inferred"


def memory_trust_score(trust: MemoryTrust) -> float:
    """Numeric view of staged trust for explain_belief / audit tooling (ADR 0008)."""
    if trust == "verified":
        return 1.0
    if trust == "quarantined":
        return 0.0
    return 0.5


def _is_truthy(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes"}
    return raw == 1


__all__ = [
    "MEMORY_EXPLICIT_WRITE_KEY",
    "MEMORY_ORIGIN_KEY",
    "MEMORY_TRUST_KEY",
    "MemoryOrigin",
    "MemoryTrust",
    "MemoryType",
    "coerce_memory_origin",
    "coerce_memory_trust",
    "memory_trust_score",
    "resolve_memory_origin",
    "resolve_memory_trust",
]
