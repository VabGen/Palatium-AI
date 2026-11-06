# src/palatium_ai/application/services/memory_sleep_consolidation.py

"""Sleep-time consolidation: corroborate → promote → retention (060, ADR 0002/0008).

Different from ``memory_extract`` (transcript → medium): this pass upgrades
inferred trust, moves eligible medium rows to the long-term graph, then applies
retention windows. Out-of-band only; forgetting stays in the retention layer —
this service never deletes rows.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from palatium_ai.application.services.retention.orchestrator import RetentionRunResult
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.policies.retention import MEMORY_RETENTION_CLASSES

if TYPE_CHECKING:
    from collections.abc import Sequence

    from palatium_ai.application.services.memory_corroboration import MemoryCorroborationService
    from palatium_ai.application.services.memory_promotion import MemoryPromotionService
    from palatium_ai.application.services.retention.orchestrator import RetentionOrchestrator

logger = get_logger(__name__)


class SleepConsolidationResult(BaseModel, frozen=True):
    """One consolidation pass: corroboration + per-user promote + retention."""

    dry_run: bool
    corroborated: dict[str, int] = Field(default_factory=dict)
    promoted: dict[str, int] = Field(default_factory=dict)
    retention: RetentionRunResult | None = None


class SleepConsolidationService:
    """Batch: trust corroboration, medium → graph promote, then retention sweep."""

    def __init__(
        self,
        *,
        promotion: MemoryPromotionService | None,
        retention: RetentionOrchestrator | None = None,
        corroboration: MemoryCorroborationService | None = None,
    ) -> None:
        self._promotion = promotion
        self._retention = retention
        self._corroboration = corroboration

    @traceable(name="memory_consolidation.run")
    async def run(
        self,
        *,
        user_ids: Sequence[str],
        limit: int = 32,
        dry_run: bool = True,
        run_promote: bool = True,
        run_retention: bool = True,
        run_corroboration: bool = True,
    ) -> SleepConsolidationResult:
        """Corroborate first so the same pass can promote freshly verified rows."""
        safe_limit = max(1, min(int(limit), 128))
        seen: set[str] = set()
        ordered_users: list[str] = []
        for raw in user_ids:
            uid = raw.strip()
            if not uid or uid in seen:
                continue
            seen.add(uid)
            ordered_users.append(uid)

        corroborated: dict[str, int] = {}
        if run_corroboration and self._corroboration is not None:
            for uid in ordered_users:
                # Snapshot size is independent of promote batch; keep a hard ceiling.
                corroborated[uid] = await self._corroboration.run_for_user(
                    user_id=uid,
                    limit=max(safe_limit * 4, 64),
                )

        promoted: dict[str, int] = {}
        if run_promote:
            if self._promotion is None:
                msg = "promotion service is required when run_promote=True"
                raise ValueError(msg)
            for uid in ordered_users:
                promoted[uid] = await self._promotion.run_batch(user_id=uid, limit=safe_limit)

        retention_result = None
        if run_retention and self._retention is not None:
            retention_result = await self._retention.run(classes=MEMORY_RETENTION_CLASSES, dry_run=dry_run)
        logger.info(
            "memory_consolidation.finished",
            dry_run=dry_run,
            users=len(ordered_users),
            corroborated=sum(corroborated.values()),
            promoted=sum(promoted.values()),
            retention_classes=len(retention_result.reports) if retention_result is not None else 0,
        )
        return SleepConsolidationResult(
            dry_run=dry_run,
            corroborated=corroborated,
            promoted=promoted,
            retention=retention_result,
        )
