"""Formatter presentation flags."""

from __future__ import annotations

from pydantic import Field

from .base import BaseConfig


class FormatterConfig(BaseConfig):
    """Runtime switches for the Formatter agent.

    Raw JSON token streaming is a debug aid. Production turns already show
    plain prose via ``answer_delta`` and the finished document via ``result``.
    """

    debug_stream_deltas: bool = Field(
        default=False,
        validation_alias="FORMATTER_DEBUG_STREAM_DELTAS",
        description=(
            "When true, FormatterAgent emits raw JSON chunks as formatter_delta. "
            "Leave false in production."
        ),
    )
