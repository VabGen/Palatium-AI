# tests/unit/test_memory_sleep_consolidation.py

"""Sleep-time consolidation service: promote per user + one retention sweep (060)."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.memory_sleep_consolidation import SleepConsolidationService
from palatium_ai.application.services.retention.orchestrator import RetentionRunResult
from palatium_ai.domain.policies.retention import MEMORY_RETENTION_CLASSES


class _FakePromotion:
    def __init__(self, counts: dict[str, int] | None = None) -> None:
        self.calls: list[tuple[str, int]] = []
        self._counts = counts or {}

    async def run_batch(self, *, user_id: str, limit: int = 32) -> int:
        self.calls.append((user_id, limit))
        return self._counts.get(user_id, 0)


class _FakeRetention:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], bool]] = []

    async def run(self, *, classes: tuple[str, ...], dry_run: bool = True, limit: int | None = None) -> RetentionRunResult:
        _ = limit
        self.calls.append((tuple(classes), dry_run))
        return RetentionRunResult(dry_run=dry_run)


@pytest.mark.asyncio()
async def test_run_promotes_each_distinct_user_then_retention_once() -> None:
    promotion = _FakePromotion({"u1": 2, "u2": 1})
    retention = _FakeRetention()
    service = SleepConsolidationService(promotion=promotion, retention=retention)  # type: ignore[arg-type]  # structural fake

    result = await service.run(user_ids=["u1", " u2 ", "", "u1"], limit=32)

    assert promotion.calls == [("u1", 32), ("u2", 32)]
    assert retention.calls == [(MEMORY_RETENTION_CLASSES, True)]
    assert result.promoted == {"u1": 2, "u2": 1}
    assert result.retention is not None
    assert result.dry_run is True


@pytest.mark.asyncio()
async def test_run_can_skip_promote_and_retention_independently() -> None:
    promotion = _FakePromotion()
    retention = _FakeRetention()
    service = SleepConsolidationService(promotion=promotion, retention=retention)  # type: ignore[arg-type]  # structural fake

    only_retention = await service.run(user_ids=["u1"], run_promote=False, dry_run=False)
    assert promotion.calls == []
    assert only_retention.promoted == {}
    assert retention.calls == [(MEMORY_RETENTION_CLASSES, False)]

    only_promote = await service.run(user_ids=["u1"], run_retention=False)
    assert promotion.calls == [("u1", 32)]
    assert only_promote.retention is None


@pytest.mark.asyncio()
async def test_run_clamps_batch_limit() -> None:
    promotion = _FakePromotion()
    service = SleepConsolidationService(promotion=promotion)  # type: ignore[arg-type]  # structural fake

    await service.run(user_ids=["u1"], limit=10_000, run_retention=False)

    assert promotion.calls == [("u1", 128)]


@pytest.mark.asyncio()
async def test_run_requires_promotion_service_when_promoting() -> None:
    service = SleepConsolidationService(promotion=None, retention=None)

    with pytest.raises(ValueError, match="promotion service is required"):
        await service.run(user_ids=["u1"])
