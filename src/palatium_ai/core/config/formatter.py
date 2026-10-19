"""Formatter presentation flags."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import BaseConfig

# Generation contract for the Formatter agent (010: single source for the axis).
#   legacy       — stream GFM Markdown, then parse it into ContentDocument + repair loop.
#   schema_first — ask the provider for a json_schema-constrained ContentDocument
#                  directly (no Markdown, no regex heuristics, no repair).
FormatterMode = Literal["legacy", "schema_first"]


class FormatterConfig(BaseConfig):
    """Runtime switches for the Formatter agent.

    Raw JSON token streaming is a debug aid. Production turns already show
    plain prose via ``answer_delta`` and the finished document via ``result``.
    """

    debug_stream_deltas: bool = Field(
        default=False,
        validation_alias="FORMATTER_DEBUG_STREAM_DELTAS",
        description=("When true, FormatterAgent emits raw JSON chunks as formatter_delta. Leave false in production."),
    )
    formatter_mode: FormatterMode = Field(
        default="legacy",
        validation_alias="FORMATTER_MODE",
        description=(
            "legacy = stream GFM Markdown then parse into ContentDocument; "
            "schema_first = provider-enforced ContentDocument json_schema (canary via env)."
        ),
    )
    formatter_rollout_pct: int = Field(
        default=0,
        ge=0,
        le=100,
        validation_alias="FORMATTER_ROLLOUT_PCT",
        description=(
            "Sticky per-user share of the schema_first contract (two-key rollout, "
            "see core/observability/formatter_rollout.py). 0 = off (safe default: a lone "
            "FORMATTER_MODE=schema_first must not flip everyone); 1..99 = canary cohort; "
            "100 = every caller (explicit full cutover)."
        ),
    )
