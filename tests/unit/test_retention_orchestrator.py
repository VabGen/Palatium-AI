# tests/unit/test_retention_orchestrator.py

"""Retention orchestrator dry-run (plans/global-retention W0)."""

from __future__ import annotations

import pytest

from palatium_ai.application.services.retention.orchestrator import RetentionOrchestrator
from palatium_ai.domain.policies.retention import DEFAULT_RETENTION_WINDOWS
from palatium_ai.domain.ports.retention import RetentionClassReport


class _CountingHandler:
    retention_class = "memory_medium"

    def __init__(self) -> None:
        self.plan_calls = 0
        self.execute_calls = 0

    async def plan(self, *, limit: int) -> RetentionClassReport:
        self.plan_calls += 1
        return RetentionClassReport(
            retention_class="memory_medium",
            action="delete",
            candidates=3,
            detail=f"limit={limit}",
        )

    async def execute(self, *, limit: int) -> RetentionClassReport:
        self.execute_calls += 1
        return RetentionClassReport(
            retention_class="memory_medium",
            action="delete",
            candidates=3,
            acted=3,
            detail=f"limit={limit}",
        )


@pytest.mark.asyncio()
async def test_dry_run_calls_plan_only() -> None:
    handler = _CountingHandler()
    orch = RetentionOrchestrator(windows=DEFAULT_RETENTION_WINDOWS, handlers={handler.retention_class: handler})
    result = await orch.run(classes=("memory_medium",), dry_run=True)
    assert result.dry_run is True
    assert handler.plan_calls == 1
    assert handler.execute_calls == 0
    assert result.reports[0].candidates == 3


@pytest.mark.asyncio()
async def test_execute_calls_handler_execute() -> None:
    handler = _CountingHandler()
    orch = RetentionOrchestrator(windows=DEFAULT_RETENTION_WINDOWS, handlers={handler.retention_class: handler})
    result = await orch.run(classes=("memory_medium",), dry_run=False)
    assert result.dry_run is False
    assert handler.execute_calls == 1
    assert result.reports[0].acted == 3


@pytest.mark.asyncio()
async def test_missing_handler_uses_policy_snapshot() -> None:
    orch = RetentionOrchestrator(windows=DEFAULT_RETENTION_WINDOWS)
    result = await orch.run(classes=("report_only",), dry_run=True)
    assert len(result.reports) == 1
    assert result.reports[0].retention_class == "report_only"
    assert result.reports[0].action == "report_only"
