# mcp_servers/analytics/contract.py

"""Frozen pydantic I/O for analytics MCP stub — mirrors platform external_schemas."""

from __future__ import annotations

import sys

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

try:
    from schema_util import pinned_input_schema
except ImportError:
    _mcp_root = Path(__file__).resolve().parent.parent
    if str(_mcp_root) not in sys.path:
        sys.path.insert(0, str(_mcp_root))
    from schema_util import pinned_input_schema

_MAX_PERIOD_CHARS = 64


class SalesMetricsInput(BaseModel):
    model_config = ConfigDict(frozen=True)

    period: str = Field(
        min_length=1,
        max_length=_MAX_PERIOD_CHARS,
        description="Reporting period (e.g. 2025-Q1).",
    )


SALES_METRICS_INPUT_SCHEMA = pinned_input_schema(SalesMetricsInput)
