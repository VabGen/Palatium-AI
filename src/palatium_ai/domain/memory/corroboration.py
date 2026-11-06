# src/palatium_ai/domain/memory/corroboration.py

"""Batch trust upgrades for inferred medium facts (ADR 0008 / CMD1.6).

Near-duplicate lexical overlap is intentional (same proxy as ``duplicates.py``):
cheap, deterministic, CI-friendly. Semantic paraphrase remains MemoryKeeper's job.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.duplicates import NEAR_DUPLICATE_JACCARD, normalize_memory_text
from palatium_ai.domain.memory.types import MemoryOrigin, MemoryTrust

_TOKEN = re.compile(r"\w+", re.UNICODE)


class CorroborationEntry(BaseModel):
    """One medium row considered for trust upgrade."""

    model_config = {"frozen": True}

    namespace: tuple[str, ...]
    entry_key: str = Field(min_length=1, max_length=256)
    text: str = Field(min_length=1, max_length=2000)
    trust: MemoryTrust
    origin: MemoryOrigin = "extract"
    source_task_id: str = Field(default="", max_length=128)


class TrustUpgrade(BaseModel):
    """Proposed ``inferred → verified`` mutation (caller persists)."""

    model_config = {"frozen": True}

    namespace: tuple[str, ...]
    entry_key: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=64)


def propose_trust_upgrades(
    entries: list[CorroborationEntry] | tuple[CorroborationEntry, ...],
    *,
    jaccard_threshold: float = NEAR_DUPLICATE_JACCARD,
) -> tuple[TrustUpgrade, ...]:
    """Return upgrades for inferred rows corroborated by verified or a second extract.

    Independence = different non-empty ``source_task_id``. Same-task restates do not count.
    """
    items = [e for e in entries if e.text.strip()]
    upgrades: list[TrustUpgrade] = []
    seen_keys: set[tuple[tuple[str, ...], str]] = set()

    verified = [e for e in items if e.trust == "verified"]
    inferred = [e for e in items if e.trust == "inferred"]

    for cand in inferred:
        key = (cand.namespace, cand.entry_key)
        if key in seen_keys:
            continue
        if _corroborated_by_verified(cand, verified, threshold=jaccard_threshold):
            upgrades.append(TrustUpgrade(namespace=cand.namespace, entry_key=cand.entry_key, reason="verified_overlap"))
            seen_keys.add(key)
            continue
        if _corroborated_by_peer_extract(cand, inferred, threshold=jaccard_threshold):
            upgrades.append(TrustUpgrade(namespace=cand.namespace, entry_key=cand.entry_key, reason="peer_extract"))
            seen_keys.add(key)
    return tuple(upgrades)


def _corroborated_by_verified(
    cand: CorroborationEntry,
    verified: list[CorroborationEntry],
    *,
    threshold: float,
) -> bool:
    for other in verified:
        if other.namespace != cand.namespace:
            continue
        if _jaccard(cand.text, other.text) >= threshold:
            return True
    return False


def _corroborated_by_peer_extract(
    cand: CorroborationEntry,
    inferred: list[CorroborationEntry],
    *,
    threshold: float,
) -> bool:
    left_task = cand.source_task_id.strip()
    if not left_task:
        return False
    for other in inferred:
        if other.entry_key == cand.entry_key and other.namespace == cand.namespace:
            continue
        if other.namespace != cand.namespace:
            continue
        right_task = other.source_task_id.strip()
        if not right_task or right_task == left_task:
            continue
        if _jaccard(cand.text, other.text) >= threshold:
            return True
    return False


def _jaccard(left: str, right: str) -> float:
    a = set(_TOKEN.findall(normalize_memory_text(left)))
    b = set(_TOKEN.findall(normalize_memory_text(right)))
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


__all__ = [
    "CorroborationEntry",
    "TrustUpgrade",
    "propose_trust_upgrades",
]
