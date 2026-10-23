# src/palatium_ai/application/services/memory_promotion.py

"""Promote medium-term memory entries into long-term graph facts (060).

EXCEPTION (020 interactive HITL): sleep-time / batch promote writes via GraphWritePort
with audit log, analogous to MemoryFactPersistenceService sleep-time save_memory.
Do not expose unattended Neo4j MERGE on the interactive hot path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.graph.write_port import GraphFactUpsert
from palatium_ai.domain.memory.bayesian_trust import BetaTrust
from palatium_ai.domain.memory.promotion import DEFAULT_PROMOTE_CLAIM_SECONDS, PromotionThresholds
from palatium_ai.domain.memory.xmemory import decouple_before_aggregate
from palatium_ai.domain.policies.promotion import PromotionPolicy

if TYPE_CHECKING:
    from palatium_ai.domain.graph.write_port import GraphWritePort
    from palatium_ai.domain.memory.promotion import PromotionCandidate
    from palatium_ai.domain.memory.promotion_port import MemoryPromotionPort

logger = get_logger(__name__)

# Why an enum-ish Literal instead of "bool promoted": a blocked PII supersede and a
# policy skip both return no node, but only the first is a *waiting human decision* that
# must be counted and surfaced (M5 audit F3). Collapsing them into False is what made
# the dead-end invisible.
PromoteOutcome = Literal["promoted", "skipped", "blocked_pii"]
_BLOCKED_SAMPLE_SIZE = 5


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
        claim_seconds: int = DEFAULT_PROMOTE_CLAIM_SECONDS,
    ) -> None:
        self._memory = memory
        self._graph_write = graph_write
        self._thresholds = thresholds or PromotionThresholds()
        self._xmemory_decouple = xmemory_decouple
        self._bayesian_trust = bayesian_trust
        self._claim_seconds = max(1, claim_seconds)

    @traceable(name="memory_promotion.run_batch")
    async def run_batch(self, *, user_id: str, limit: int = 32) -> int:
        """Promote eligible rows for one RLS user_id; returns successful upserts."""
        uid = user_id.strip()
        if not uid:
            return 0
        # Floor access=0 so preferences (promote-on-write) appear; Policy applies
        # kind-specific bars for episodic facts (060 / SB4).
        candidates = await self._memory.list_promotion_candidates(
            user_id=uid,
            min_access_frequency=0,
            min_importance=self._thresholds.min_importance,
            limit=max(1, min(limit, 128)),
        )
        if self._xmemory_decouple:
            candidates = decouple_before_aggregate(list(candidates))
        promoted = 0
        blocked: list[str] = []
        for candidate in candidates:
            outcome = await self._try_promote(candidate)
            if outcome == "promoted":
                promoted += 1
            elif outcome == "blocked_pii":
                blocked.append(candidate.entry_key)
        # One line per batch, not per candidate: an unresolved PII conflict is retried on
        # every run until a human decides, so per-candidate warnings would grow unbounded
        # and drown the signal they carry.
        if blocked:
            agent_metrics.record_memory_promote_blocked_pii(count=len(blocked))
            logger.warning(
                "memory_promotion.blocked_pii_supersede",
                user_id=uid,
                blocked=len(blocked),
                entry_keys=blocked[:_BLOCKED_SAMPLE_SIZE],
                entry_keys_truncated=len(blocked) > _BLOCKED_SAMPLE_SIZE,
            )
        return promoted

    async def _try_promote(self, candidate: PromotionCandidate) -> PromoteOutcome:
        if not PromotionPolicy.should_promote(candidate, thresholds=self._thresholds):
            return "skipped"
        # Claim before the graph write: listing then writing is a read-then-write pair, and
        # two promoters (schedule + operator CLI) that both saw "not promoted" would write
        # the same version twice (M5 audit F6). A lost claim is not a failure — the other
        # promoter owns the row and will mark it.
        claimed = await self._memory.claim_promotion(
            namespace=candidate.namespace,
            key=candidate.entry_key,
            lease_seconds=self._claim_seconds,
        )
        if not claimed:
            return "skipped"
        outcome: PromoteOutcome = "skipped"
        try:
            outcome = await self._promote_claimed(candidate)
        finally:
            if outcome != "promoted":
                # Blocked/skipped/failed attempts return the row to the candidate pool now
                # instead of after the lease: a blocked PII row must stay visible in the
                # per-batch counter, and a failed write must be retried on the next run.
                await self._release_claim(candidate)
        return outcome

    async def _promote_claimed(self, candidate: PromotionCandidate) -> PromoteOutcome:
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
            # GraphWritePort documents "" as exactly one thing: a blocked PII supersede.
            # Counted/logged once per batch by run_batch (not here) — see F3.
            return "blocked_pii"
        marked = await self._memory.mark_promoted(
            namespace=candidate.namespace,
            key=candidate.entry_key,
        )
        if not marked:
            return "skipped"
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
        return "promoted"

    async def _release_claim(self, candidate: PromotionCandidate) -> None:
        try:
            await self._memory.release_promotion(
                namespace=candidate.namespace,
                key=candidate.entry_key,
            )
        except Exception as exc:  # noqa: BLE001  # release is best-effort: the lease expires anyway
            logger.warning(
                "memory_promotion.claim_release_failed",
                entry_key=candidate.entry_key[:128],
                error=str(exc),
            )


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
    except Exception as exc:  # noqa: BLE001  # audit write is best-effort; the promote result is kept (040)
        logger.warning("memory_promotion.audit_failed", error=str(exc))
