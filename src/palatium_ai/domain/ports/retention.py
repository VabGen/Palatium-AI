# src/palatium_ai/domain/ports/retention.py

"""Ports for retention class handlers (plans/global-retention.md)."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.retention import RetentionAction, RetentionClass


class RetentionClassReport(BaseModel, frozen=True):
    """Dry-run / execute counters for one retention class."""

    retention_class: RetentionClass
    action: RetentionAction
    candidates: int = Field(default=0, ge=0)
    acted: int = Field(default=0, ge=0)
    held: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    detail: str = ""


class RetentionClassHandler(Protocol):
    """One store adapter behind the orchestrator.

    ``retention_class`` is a property (not a mutable attribute): Protocol mutable
    attrs are invariant and basedpyright rejects concrete handlers that assign the
    field in ``__init__``. Orchestrator only reads the key for routing.
    """

    @property
    def retention_class(self) -> RetentionClass:
        """Stable RetentionClass key for this handler."""
        ...

    async def plan(self, *, limit: int) -> RetentionClassReport:
        """Count candidates without mutating."""
        ...

    async def execute(self, *, limit: int) -> RetentionClassReport:
        """Apply disposition for up to ``limit`` candidates."""
        ...
