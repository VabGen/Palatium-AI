# src/palatium_ai/domain/policies/response_cache.py

"""L1 response cache key policy (latency P0.2, 055).

Exact-match key for tenant-scoped Formatter results. Pure — no I/O.
``ack_only`` is not cacheable: live social uses Formatter LLM (format_only).
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import LOW_RISK_ROUTE_STRATEGIES, ExecutionStrategy

_WHITESPACE = re.compile(r"\s+")


class ResponseCacheKeyParts(BaseModel):
    """Inputs that fully determine an L1 cache key."""

    model_config = {"frozen": True}

    tenant_key: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=128)
    system_fingerprint: str = Field(min_length=1, max_length=64)
    user_norm: str = Field(min_length=0, max_length=8_000)
    strategy: ExecutionStrategy
    locale: str = Field(min_length=2, max_length=16)


class ResponseCacheKeyPolicy:
    """Build and classify L1 response-cache keys."""

    @staticmethod
    def normalize_user_text(text: str) -> str:
        """Collapse whitespace and lowercase for exact-repeat matching."""
        return _WHITESPACE.sub(" ", text.strip().lower())

    @classmethod
    def build_key(cls, parts: ResponseCacheKeyParts) -> str:
        """Return Redis-safe key: ``palatium:l1:<sha256>``."""
        payload = "|".join(
            (
                parts.tenant_key,
                parts.model,
                parts.system_fingerprint,
                parts.user_norm,
                parts.strategy,
                parts.locale,
            )
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"palatium:l1:{digest}"

    @classmethod
    def is_cacheable_strategy(cls, strategy: str) -> bool:
        """Only low-risk strategies may populate the L1 response cache."""
        return strategy in LOW_RISK_ROUTE_STRATEGIES or strategy == "clarify"
