# src/palatium_ai/core/types/w78_observability.py

"""Closed label sets for W7–W8 cost / retry / schema / cap metrics (040, ADR-0011)."""

from __future__ import annotations

from typing import Final, Literal, get_args

#: ``palatium_llm_tokens_total{direction}`` — input = prompt, output = completion.
LLMTokenDirection = Literal["input", "output"]

#: Outcome of a single retry decision (LLM or tool).
RetryOutcome = Literal["retried", "exhausted", "not_retryable", "verify_skip"]

#: Why harness schema gate rejected an agent output (before agent.verify / LLM-judge).
SchemaMismatchReason = Literal["type_mismatch", "missing_output", "unregistered_role"]

#: Which concurrency ceiling was hit.
SubagentCapKind = Literal["max_parallel", "max_total"]

LLM_TOKEN_DIRECTIONS: Final[frozenset[str]] = frozenset(get_args(LLMTokenDirection))
RETRY_OUTCOMES: Final[frozenset[str]] = frozenset(get_args(RetryOutcome))
SCHEMA_MISMATCH_REASONS: Final[frozenset[str]] = frozenset(get_args(SchemaMismatchReason))
SUBAGENT_CAP_KINDS: Final[frozenset[str]] = frozenset(get_args(SubagentCapKind))


def coerce_llm_token_direction(direction: str | None) -> LLMTokenDirection:
    value = (direction or "").strip().lower()
    if value in {"input", "prompt"}:
        return "input"
    if value in {"output", "completion"}:
        return "output"
    return "input"


__all__ = [
    "LLM_TOKEN_DIRECTIONS",
    "RETRY_OUTCOMES",
    "SCHEMA_MISMATCH_REASONS",
    "SUBAGENT_CAP_KINDS",
    "LLMTokenDirection",
    "RetryOutcome",
    "SchemaMismatchReason",
    "SubagentCapKind",
    "coerce_llm_token_direction",
]
