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
from palatium_ai.domain.memory.promotion import PromotionThresholds
from palatium_ai.domain.policies.promotion import PromotionPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.graph.write_port import GraphWritePort
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
    ) -> None:
        self._memory = memory
        self._graph_write = graph_write
        self._thresholds = thresholds or PromotionThresholds()

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
        promoted = 0
        for candidate in candidates:
            if not PromotionPolicy.should_promote(candidate, thresholds=self._thresholds):
                continue
            importance = PromotionPolicy.effective_importance(candidate)
            thread_id = ""
            if len(candidate.namespace) >= 3 and candidate.namespace[0] == "chat":
                thread_id = candidate.namespace[2]
            node_id = await self._graph_write.upsert_fact(
                GraphFactUpsert(
                    user_id=candidate.user_id,
                    entry_key=candidate.entry_key,
                    text=candidate.text,
                    kind=candidate.kind,
                    importance=importance,
                    source_namespace=candidate.namespace,
                    thread_id=thread_id,
                )
            )
            marked = await self._memory.mark_promoted(
                namespace=candidate.namespace,
                key=candidate.entry_key,
            )
            if marked:
                promoted += 1
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
        return promoted


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
