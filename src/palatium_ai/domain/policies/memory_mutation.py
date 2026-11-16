# src/palatium_ai/domain/policies/memory_mutation.py

"""Deterministic targeting for interactive memory mutations (060, 070; E2E-01/03).

The Intent classifier names the axis and its payload (``memory_mutation`` /
``memory_text`` / ``memory_key``); this policy turns that payload into a stable
entry key and resolves an existing medium-memory target for a forget ask. Pure
(no I/O) so the mutation gate and unit tests share one truth (055).
"""

from __future__ import annotations

import hashlib
import re

from palatium_ai.core.types.coerce import coerce_float

_TOKEN_RE = re.compile(r"[a-zа-я0-9_]{2,}")
_KEY_SEPARATORS = re.compile(r"[^a-z0-9_]+")
_WHITESPACE_RE = re.compile(r"\s+")

#: Digest-derived keys are namespaced so they can never collide with a model-supplied
#: slug (``db_port`` — underscores are kept), and stay short for the HITL preview.
MEMORY_KEY_PREFIX = "mem-"
MEMORY_KEY_MAX_CHARS = 64
MEMORY_TEXT_MAX_CHARS = 2_000
#: Interactive mutations target owner-scoped memory: the fact must survive the thread
#: (E2E-01). Thread memory is written by sleep-time extract, not by this gate (060).
INTERACTIVE_NAMESPACE_KIND = "user"
#: Overlap coefficient (|A∩B| / min(|A|,|B|)) above which a stored entry is treated as
#: the same subject. Values differ on purpose: «порт базы 5433» vs «порт базы данных
#: 5432» shares the subject, which makes an update a supersede, not a new fact; while
#: two different objects sharing one verb («люблю кофе» vs «люблю чай», 0.5) stay
#: separate facts.
MIN_EXISTING_OVERLAP = 0.6


class MemoryMutationPolicy:
    """Normalize the mutation payload; pick the entry this turn must update/forget."""

    @staticmethod
    def normalize_text(text: str) -> str:
        """Collapse whitespace and trim surrounding quotes/punctuation (no rewriting)."""
        collapsed = _WHITESPACE_RE.sub(" ", text or "").strip()
        return collapsed.strip("\"'«»“”` ").strip()

    @classmethod
    def coerce_text(cls, raw: object) -> str:
        """Model payload → bounded statement; empty means "nothing to act on"."""
        if not isinstance(raw, str):
            return ""
        return cls.normalize_text(raw)[:MEMORY_TEXT_MAX_CHARS].strip()

    @classmethod
    def query_tokens(cls, text: str) -> frozenset[str]:
        return frozenset(_TOKEN_RE.findall((text or "").lower()))

    @classmethod
    def coerce_key(cls, raw: object, *, text: str) -> str:
        """Model key hint → slug; absent/garbage falls back to a statement digest."""
        candidate = raw.strip().lower() if isinstance(raw, str) else ""
        slug = _KEY_SEPARATORS.sub("-", candidate).strip("-")
        slug = slug[:MEMORY_KEY_MAX_CHARS].strip("-")
        if slug:
            return slug
        digest = hashlib.sha256(cls.normalize_text(text).lower().encode("utf-8")).hexdigest()[:12]
        return f"{MEMORY_KEY_PREFIX}{digest}"

    @classmethod
    def overlap_ratio(cls, left: str, right: str) -> float:
        """Overlap coefficient (|A∩B| / min(|A|,|B|)) of two statements' tokens."""
        a = cls.query_tokens(left)
        b = cls.query_tokens(right)
        if not a or not b:
            return 0.0
        return len(a & b) / min(len(a), len(b))

    @classmethod
    def shares_subject(cls, left: str, right: str, *, threshold: float = MIN_EXISTING_OVERLAP) -> bool:
        """Same subject? Used to purge caches (thread scratchpad) when a fact is forgotten."""
        return cls.overlap_ratio(left, right) >= threshold

    @classmethod
    def best_existing_match(
        cls,
        hits: list[dict[str, object]],
        *,
        text: str,
    ) -> dict[str, object] | None:
        """Closest stored entry for ``text`` — or None when nothing overlaps enough.

        Only hits carrying an entry key are candidates: an entry without a key cannot
        be addressed by ``save_memory``/``forget_memory`` (070), so it is not a target.
        """
        wanted = cls.query_tokens(text)
        if not wanted:
            return None
        ranked: list[tuple[float, float, dict[str, object]]] = []
        for hit in hits:
            key = str(hit.get("_entry_key") or "").strip()
            body = str(hit.get("text") or "")
            if not key or not body.strip():
                continue
            stored = cls.query_tokens(body)
            if not stored:
                continue
            overlap = cls.overlap_ratio(text, body)
            if overlap < MIN_EXISTING_OVERLAP:
                continue
            ranked.append((overlap, cls._hit_score(hit), hit))
        if not ranked:
            return None
        ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return ranked[0][2]

    @staticmethod
    def _hit_score(hit: dict[str, object]) -> float:
        return coerce_float(hit.get("_score"))
