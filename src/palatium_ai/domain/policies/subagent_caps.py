# src/palatium_ai/domain/policies/subagent_caps.py

"""Concurrency caps for parallel / nested subagents (W8.5, ADR-0011)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from palatium_ai.core.types.w78_observability import SubagentCapKind


class SubagentCapExceededError(RuntimeError):
    """Raised when a concurrency ceiling is hit — never silent drop."""

    def __init__(self, *, cap: SubagentCapKind, limit: int, requested: int) -> None:
        self.cap = cap
        self.limit = limit
        self.requested = requested
        super().__init__(f"subagent cap exceeded: {cap} limit={limit} requested={requested}")


class SubagentCaps(BaseModel):
    """Runtime ceilings — values from settings / behavioral baseline."""

    model_config = {"frozen": True}

    max_parallel_subagents: int = Field(default=2, ge=1)
    max_total_subagents_per_run: int = Field(default=4, ge=1)


class SubagentCapPolicy:
    """Fail-closed enforcement — exceed → ``SubagentCapExceededError``."""

    def __init__(self, caps: SubagentCaps | None = None) -> None:
        self._caps = caps or SubagentCaps()

    @property
    def caps(self) -> SubagentCaps:
        return self._caps

    def assert_parallel(self, requested: int) -> None:
        if requested > self._caps.max_parallel_subagents:
            raise SubagentCapExceededError(
                cap="max_parallel",
                limit=self._caps.max_parallel_subagents,
                requested=requested,
            )

    def assert_total(self, *, already_spawned: int, additional: int) -> None:
        total = already_spawned + additional
        if total > self._caps.max_total_subagents_per_run:
            raise SubagentCapExceededError(
                cap="max_total",
                limit=self._caps.max_total_subagents_per_run,
                requested=total,
            )


__all__ = [
    "SubagentCapExceededError",
    "SubagentCapPolicy",
    "SubagentCaps",
]
