# src/palatium_ai/domain/policies/llm_retry.py

"""Unified LLM/tool retry classification — transient vs permanent (W8.3, ADR-0011)."""

from __future__ import annotations

from typing import Final

from palatium_ai.core.exceptions import AgentExecutionError
from palatium_ai.core.resilience import CircuitOpenError, RetryPolicy
from palatium_ai.core.types.w78_observability import RetryOutcome
from palatium_ai.domain.llm.errors import EmptyLLMCompletionError, StructuredOutputUnsupportedError

#: HTTP / provider codes treated as transient (retryable).
_TRANSIENT_STATUS_MARKERS: Final[frozenset[str]] = frozenset(
    {
        "429",
        "500",
        "502",
        "503",
        "504",
        "timeout",
        "timed out",
        "temporarily",
        "unavailable",
        "connection reset",
        "connection aborted",
    }
)

#: Permanent client/validation failures — never retry.
_PERMANENT_TYPE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "ValidationError",
        "ValueError",
        "TypeError",
        "PermissionError",
        "AuthenticationError",
        "BadRequestError",
        "InvalidRequestError",
    }
)


#: Shared backoff defaults for LLM *and* tool retries (W8.3 / ADR-0011).
#: MCP / ToolExecutor must use the same ``RetryPolicy`` shape — not a second ad-hoc loop.
SHARED_RETRY_INITIAL_DELAY_SECONDS: Final[float] = 1.0
SHARED_RETRY_MAX_DELAY_SECONDS: Final[float] = 8.0


def default_retry_policy(*, max_attempts: int) -> RetryPolicy:
    """Single backoff config for LLM and tools (W8.3)."""
    attempts = max(1, max_attempts)
    return RetryPolicy(
        max_attempts=attempts,
        initial_delay_seconds=SHARED_RETRY_INITIAL_DELAY_SECONDS,
        max_delay_seconds=SHARED_RETRY_MAX_DELAY_SECONDS,
    )


def default_llm_retry_policy(*, max_attempts: int) -> RetryPolicy:
    """Alias kept for harness call sites — same as :func:`default_retry_policy`."""
    return default_retry_policy(max_attempts=max_attempts)


def is_transient_llm_error(exc: BaseException) -> bool:
    """True only for timeout / 5xx / empty-completion class failures."""
    if isinstance(exc, (TimeoutError, EmptyLLMCompletionError)):
        return True
    if isinstance(
        exc,
        (
            StructuredOutputUnsupportedError,
            CircuitOpenError,
            AgentExecutionError,
        ),
    ):
        return False
    name = type(exc).__name__
    if name in {"CostBudgetExceededError", *_PERMANENT_TYPE_NAMES}:
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        if 400 <= status < 500 and status != 429:
            return False
        if status >= 500 or status == 429:
            return True
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_STATUS_MARKERS)


def classify_retry_decision(
    *,
    exc: BaseException | None,
    attempt: int,
    max_attempts: int,
    verify_failed: bool = False,
) -> RetryOutcome:
    """Closed outcome label for metrics / tests (verify failures never retry)."""
    if verify_failed:
        return "verify_skip"
    if exc is None:
        return "not_retryable"
    if not is_transient_llm_error(exc):
        return "not_retryable"
    if attempt >= max_attempts:
        return "exhausted"
    return "retried"


__all__ = [
    "SHARED_RETRY_INITIAL_DELAY_SECONDS",
    "SHARED_RETRY_MAX_DELAY_SECONDS",
    "classify_retry_decision",
    "default_llm_retry_policy",
    "default_retry_policy",
    "is_transient_llm_error",
]
