# src/palatium_ai/core/types/extract_queue.py

"""Admission limits of the durable extract queue — numeric defaults (M3 audit E7).

The values live in ``core/`` because both the settings layer (``core/config/memory.py``)
and the domain contract (``domain/memory/extract_queue.py``) need them, and ``core`` must
not import ``domain`` (rule 000). Keeping one copy here avoids two drifting defaults (010,
050); the domain module re-exports these names as part of its public contract.
"""

from __future__ import annotations

#: Default backlog ceiling for ``pending + running`` jobs across all owners.
DEFAULT_MAX_QUEUE = 256

#: The queue must hold at least this many *full owner quotas*, otherwise a per-owner cap is
#: not a cap but the global limit under another name. 4 = one noisy owner plus room for the
#: others while it is saturated (M3 audit E7).
MIN_TENANT_SLOTS = 4


def fair_share_queue_cap(max_queue: int) -> int:
    """Per-owner ceiling implied by the global one: ``max_queue // MIN_TENANT_SLOTS``."""
    return max(1, int(max_queue) // MIN_TENANT_SLOTS)
