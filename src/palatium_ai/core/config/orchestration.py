# src/palatium_ai/core/config/orchestration.py

"""Orchestration runtime caps (W8.5) — parallel / total subagent ceilings."""

from __future__ import annotations

from pydantic import Field

from palatium_ai.core.config.base import BaseConfig


class OrchestrationConfig(BaseConfig):
    """LangGraph fan-out ceilings — exceed → explicit error (ADR-0011)."""

    max_parallel_subagents: int = Field(
        default=2,
        ge=1,
        validation_alias="ORCHESTRATION_MAX_PARALLEL_SUBAGENTS",
    )
    max_total_subagents_per_run: int = Field(
        default=4,
        ge=1,
        validation_alias="ORCHESTRATION_MAX_TOTAL_SUBAGENTS_PER_RUN",
    )
