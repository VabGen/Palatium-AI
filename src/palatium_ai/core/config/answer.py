# src/palatium_ai/core/config/answer.py

"""Answer-writer rollout flags (single-writer contract, P1a).

Two keys, same semantics as the Formatter canary (``formatter.py``):
``ANSWER_WRITER_MODE`` selects the *target* owner, ``ANSWER_WRITER_ROLLOUT_PCT``
selects *coverage* sticky by ``thread_id``. Rollback is one variable (PCT=0);
a lone ``MODE=worker`` must never flip every turn.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .base import BaseConfig

AnswerWriterMode = Literal["worker", "formatter"]


class AnswerWriterConfig(BaseConfig):
    """Runtime switches for the single-writer answer contract."""

    writer_mode: AnswerWriterMode = Field(
        default="formatter",
        validation_alias="ANSWER_WRITER_MODE",
        description=(
            "worker = the worker writes the final GFM and the Formatter renders it "
            "deterministically; formatter = the Formatter is the only writer (current "
            "contract, safe default)."
        ),
    )
    writer_rollout_pct: int = Field(
        default=0,
        ge=0,
        le=100,
        validation_alias="ANSWER_WRITER_ROLLOUT_PCT",
        description=(
            "Sticky share of threads (by thread_id) that may use worker ownership. "
            "0 = off (a lone ANSWER_WRITER_MODE=worker must not flip everyone); "
            "1..99 = canary cohort; 100 = every eligible turn."
        ),
    )
