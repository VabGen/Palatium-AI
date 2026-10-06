# src/palatium_ai/application/services/memory_promotion.py

"""Promote medium-term memory entries into long-term graph facts (060).

EXCEPTION (020 interactive HITL): sleep-time / batch promote writes via GraphWritePort
with audit log, analogous to MemoryFactPersistenceService sleep-time save_memory.
Do not expose unattended Neo4j MERGE on the interactive hot path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.domain.memory.bayesian_trust import BetaTrust
from palatium_ai.domain.memory.promotion import PromotionThresholds
from palatium_ai.domain.memory.xmemory import decouple_before_aggregate
from palatium_ai.domain.policies.promotion import PromotionPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.graph.write_port import GraphWritePort
    from palatium_ai.domain.memory.promotion import PromotionCandidate
    from palatium_ai.domain.memory.promotion_port import MemoryPromotionPort

logger = get_logger(__name__)


class MemoryPromotionService:
    """Batch: list candidates → policy gate → graph upsert → mark promoted."""

    def __init__(
        self,
        *,
        memory: MemoryPromotionPort,
        graph_write: GraphWritePort,
        thresholds: PromotionThresholds | None = None,
        xmemory_decouple: bool = False,
        bayesian_trust: bool = False,
        hebbian_edge_bump: bool = False,
    ) -> None:
        self._memory = memory
        self._graph_write = graph_write
        self._thresholds = thresholds or PromotionThresholds()
        self._xmemory_decouple = xmemory_decouple
        self._bayesian_trust = bayesian_trust
        self._hebbian_edge_bump = hebbian_edge_bump

    @traceable(name="memory_promotion.run_batch")
    async def run_batch(self, *, user_id: str, limit: int = 32) -> int:
        """Promote eligible rows for one RLS user_id; returns successful upserts."""
        uid = user_id.strip()
        if not uid:
            return 0
        candidates = await self._memory.list_promotion_candidates(
            user_id=uid,
            min_access_frequency=self._thresholds.min_access_frequency,
            min_importance=self._thresholds.min_importance,
            limit=max(1, min(limit, 128)),
        )
        if self._xmemory_decouple:
            candidates = decouple_before_aggregate(list(candidates))
        promoted = 0
        for candidate in candidates:
            if await self._try_promote(candidate):
                promoted += 1
        return promoted

    async def _try_promote(self, candidate: PromotionCandidate) -> bool:
        if not PromotionPolicy.should_promote(candidate, thresholds=self._thresholds):
            return False
        importance = PromotionPolicy.effective_importance(candidate)
        confidence = candidate.confidence
        if self._bayesian_trust:
            confidence = BetaTrust.from_confidence(candidate.confidence).observe_success().mean()
        node_id = await self._graph_write.upsert_fact(
            GraphFactUpsert(
                user_id=candidate.user_id,
                entry_key=candidate.entry_key,
                text=candidate.text,
                kind=candidate.kind,
                importance=importance,
                confidence=confidence,
                source_namespace=candidate.namespace,
                thread_id=_thread_id_from_namespace(candidate.namespace),
                source_type="promote",
                contains_pii=candidate.contains_pii,
            )
        )
        if not node_id:
            logger.warning(
                "memory_promotion.blocked_pii_supersede",
                entry_key=candidate.entry_key,
                user_id=candidate.user_id,
            )
            return False
        if self._hebbian_edge_bump:
            await self._graph_write.bump_hebbian_on_entry(
                user_id=candidate.user_id,
                entry_key=candidate.entry_key,
            )
        marked = await self._memory.mark_promoted(
            namespace=candidate.namespace,
            key=candidate.entry_key,
        )
        if not marked:
            return False
        logger.info(
            "memory_promotion.promoted",
            entry_key=candidate.entry_key,
            user_id=candidate.user_id,
            node_id=node_id,
            access_frequency=candidate.access_frequency,
            importance=importance,
        )
        await _audit_promoted(
            entry_key=candidate.entry_key,
            user_id=candidate.user_id,
            node_id=node_id,
            access_frequency=candidate.access_frequency,
        )
        return True


def _thread_id_from_namespace(namespace: tuple[str, ...]) -> str:
    if len(namespace) >= 3 and namespace[0] == "chat":
        return namespace[2]
    return ""


async def _audit_promoted(
    *,
    entry_key: str,
    user_id: str,
    node_id: str,
    access_frequency: int,
) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        await get_audit_logger().append_async(
            timestamp=timestamp,
            conversation_id="memory-promote",
            event="memory_promoted",
            metadata={
                "entry_key": entry_key[:128],
                "user_id": user_id[:128],
                "node_id": node_id[:64],
                "access_frequency": str(access_frequency),
            },
        )
    except Exception as exc:
        logger.warning("memory_promotion.audit_failed", error=str(exc))
