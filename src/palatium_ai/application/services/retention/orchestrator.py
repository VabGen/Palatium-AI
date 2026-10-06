# src/palatium_ai/application/services/retention/orchestrator.py

"""Run retention class handlers with dry-run default (020 / plans/global-retention)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.policies.retention import (
    ALL_RETENTION_CLASSES,
    RetentionClass,
    RetentionPolicy,
    RetentionWindows,
)
from palatium_ai.domain.ports.retention import RetentionClassHandler, RetentionClassReport

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

logger = get_logger(__name__)


class RetentionRunResult(BaseModel, frozen=True):
    """Aggregate outcome of one job pass."""

    dry_run: bool
    reports: tuple[RetentionClassReport, ...] = ()
    lease_skipped: bool = False


class PolicySnapshotHandler:
    """W0 placeholder: reports policy disposition without touching stores."""

    def __init__(self, retention_class: RetentionClass, *, windows: RetentionWindows) -> None:
        self.retention_class = retention_class
        self._windows = windows

    async def plan(self, *, limit: int) -> RetentionClassReport:
        decision = RetentionPolicy.decide(self.retention_class)
        return RetentionClassReport(
            retention_class=self.retention_class,
            action=decision.action,
            candidates=0,
            detail=f"policy:{decision.reason};batch_cap={limit};windows_batch={self._windows.batch_size}",
        )

    async def execute(self, *, limit: int) -> RetentionClassReport:
        # Snapshot handlers never mutate; execute == plan until a real adapter is wired.
        return await self.plan(limit=limit)


class RetentionOrchestrator:
    """Dispatch enabled classes; dry-run never calls execute on mutating handlers."""

    def __init__(
        self,
        *,
        windows: RetentionWindows,
        handlers: Mapping[RetentionClass, RetentionClassHandler] | None = None,
    ) -> None:
        self._windows = windows
        self._handlers = dict(handlers or {})

    def register(self, handler: RetentionClassHandler) -> None:
        self._handlers[handler.retention_class] = handler

    async def run(
        self,
        *,
        classes: Sequence[RetentionClass] | None = None,
        dry_run: bool = True,
        limit: int | None = None,
    ) -> RetentionRunResult:
        batch = self._windows.batch_size if limit is None else max(1, min(limit, 5000))
        selected = tuple(classes) if classes is not None else ALL_RETENTION_CLASSES
        reports: list[RetentionClassReport] = []
        for retention_class in selected:
            handler = self._handlers.get(retention_class)
            if handler is None:
                handler = PolicySnapshotHandler(retention_class, windows=self._windows)
            if dry_run:
                report = await handler.plan(limit=batch)
            else:
                report = await handler.execute(limit=batch)
            reports.append(report)
            logger.info(
                "retention.class_finished",
                retention_class=retention_class,
                dry_run=dry_run,
                action=report.action,
                candidates=report.candidates,
                acted=report.acted,
                held=report.held,
                failed=report.failed,
            )
        return RetentionRunResult(dry_run=dry_run, reports=tuple(reports))
