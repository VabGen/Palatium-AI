"""Unit tests for Redis CostTracker (Phase 3)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from palatium_ai.core.observability.cost_tracker import CostTracker


@pytest.mark.asyncio()
async def test_cost_tracker_record() -> None:
    redis = AsyncMock()
    tracker = CostTracker(redis)

    await tracker.record(
        org_id="org-123",
        user_id="user-456",
        agent_role="formatter",
        model="tier-small",
        cost_usd=0.00123,
    )

    assert redis.hincrbyfloat.call_count == 2
    assert redis.expire.call_count == 2


@pytest.mark.asyncio()
async def test_cost_tracker_skips_non_positive() -> None:
    redis = AsyncMock()
    tracker = CostTracker(redis)

    await tracker.record(
        org_id="org-123",
        user_id="user-456",
        agent_role="formatter",
        model="tier-small",
        cost_usd=0.0,
    )

    assert redis.hincrbyfloat.call_count == 0
