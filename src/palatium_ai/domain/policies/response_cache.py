# src/palatium_ai/domain/policies/response_cache.py

"""L1 response cache key policy (latency P0.2, 055).

Exact-match key for Formatter results. Pure — no I/O.
``ack_only`` is not cacheable: live social uses Formatter LLM (format_only).

The key is scoped to the conversation *and* to the dialog state the turn ran in
(``prior_fingerprint``): the same sentence means different things after different
answers, so tenant + text alone replayed an unrelated turn's answer. Only
self-contained ``new_topic`` turns are cacheable at all (``is_turn_cacheable``):
a prior-dependent or upload turn is generated for this turn's context and must
never be served from an earlier one.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field

from palatium_ai.domain.memory.turns import DialogTurnWindow
from palatium_ai.domain.policies.types import LOW_RISK_ROUTE_STRATEGIES, ExecutionStrategy

_WHITESPACE = re.compile(r"\s+")
# Bump when key material / Formatter social contract changes (invalidates L1 echoes).
_SYSTEM_FINGERPRINT_SUFFIX = "v4"
_PRIOR_FINGERPRINT_CHARS = 32


class ResponseCacheKeyParts(BaseModel):
    """Inputs that fully determine an L1 cache key."""

    model_config = {"frozen": True}

    tenant_key: str = Field(min_length=1, max_length=256)
    thread_key: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=128)
    system_fingerprint: str = Field(min_length=1, max_length=64)
    user_norm: str = Field(min_length=0, max_length=8_000)
    strategy: ExecutionStrategy
    locale: str = Field(min_length=2, max_length=16)
    source_fingerprint: str = Field(default="none", min_length=1, max_length=64)
    #: Last assistant turn of the pre-turn dialog window (task id, else content).
    prior_fingerprint: str = Field(default="none", min_length=1, max_length=64)


class ResponseCacheKeyPolicy:
    """Build and classify L1 response-cache keys."""

    @staticmethod
    def normalize_user_text(text: str) -> str:
        """Collapse whitespace and lowercase for exact-repeat matching."""
        return _WHITESPACE.sub(" ", text.strip().lower())

    @classmethod
    def fingerprint_source(cls, source_content: str) -> str:
        """Stable short hash of source content, or ``none`` when empty."""
        norm = cls.normalize_user_text(source_content)
        if not norm:
            return "none"
        return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:32]

    @classmethod
    def fingerprint_prior(cls, window: DialogTurnWindow | None) -> str:
        """Fingerprint the dialog state a turn is about to extend.

        Uses the last assistant turn's task id (fallback: its content): two threads
        that happen to ask the same words after different answers must not share an
        entry, and a new independent ask must not inherit the previous turn's echo.
        """
        if window is None or not window.turns:
            return "none"
        for turn in reversed(window.turns):
            if turn.role != "assistant":
                continue
            # Task id + body: a regenerated answer keeps the id but changes the text,
            # and the next turn's key must change with it.
            material = f"{turn.task_id or ''}\x00{turn.content}".strip()
            if not material:
                return "none"
            return hashlib.sha256(material.encode("utf-8")).hexdigest()[:_PRIOR_FINGERPRINT_CHARS]
        return "none"

    @classmethod
    def system_fingerprint_for(cls, strategy: str) -> str:
        """Versioned strategy fingerprint for L1 keys."""
        return f"{strategy}_{_SYSTEM_FINGERPRINT_SUFFIX}"

    @classmethod
    def build_key(cls, parts: ResponseCacheKeyParts) -> str:
        """Return Redis-safe key: ``palatium:l1:<sha256>``."""
        payload = "|".join(
            (
                parts.tenant_key,
                parts.thread_key,
                parts.model,
                parts.system_fingerprint,
                parts.user_norm,
                parts.strategy,
                parts.locale,
                parts.source_fingerprint,
                parts.prior_fingerprint,
            )
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"palatium:l1:{digest}"

    @classmethod
    def is_cacheable_strategy(cls, strategy: str) -> bool:
        """Only low-risk strategies may populate the L1 response cache."""
        return strategy in LOW_RISK_ROUTE_STRATEGIES or strategy == "clarify"

    @classmethod
    def is_turn_cacheable(
        cls,
        *,
        strategy: str,
        continuation_kind: str | None,
        trust_prior_for_workers: bool,
        has_turn_attachments: bool,
    ) -> bool:
        """L1 is an exact-repeat cache for self-contained turns only.

        A continuation (``answer`` / ``format`` / ``clarify`` with prior) is generated
        *for* the current dialog state; replaying its result on a later turn is the
        context-bleed bug this policy exists to prevent (055). An upload turn owns its
        fence and is never cached either.
        """
        if has_turn_attachments or trust_prior_for_workers:
            return False
        # Fail closed: no explicit Continuity signal means "unknown", not "new_topic".
        if continuation_kind != "new_topic":
            return False
        return cls.is_cacheable_strategy(strategy)
