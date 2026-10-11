# src/palatium_ai/domain/policies/response_cache.py

"""L1 response cache key policy (latency P0.2, 055).

Exact-match key for tenant-scoped Formatter results. Pure — no I/O.
``ack_only`` is not cacheable: live social uses Formatter LLM (format_only).
Keys include a source fingerprint so prior-dependent format turns cannot collide.
"""

from __future__ import annotations

import hashlib
import re

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import LOW_RISK_ROUTE_STRATEGIES, ExecutionStrategy

_WHITESPACE = re.compile(r"\s+")
# Bump when key material / Formatter social contract changes (invalidates L1 echoes).
_SYSTEM_FINGERPRINT_SUFFIX = "v3"


class ResponseCacheKeyParts(BaseModel):
    """Inputs that fully determine an L1 cache key."""

    model_config = {"frozen": True}

    tenant_key: str = Field(min_length=1, max_length=256)
    model: str = Field(min_length=1, max_length=128)
    system_fingerprint: str = Field(min_length=1, max_length=64)
    user_norm: str = Field(min_length=0, max_length=8_000)
    strategy: ExecutionStrategy
    locale: str = Field(min_length=2, max_length=16)
    source_fingerprint: str = Field(default="none", min_length=1, max_length=64)


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
    def system_fingerprint_for(cls, strategy: str) -> str:
        """Versioned strategy fingerprint for L1 keys."""
        return f"{strategy}_{_SYSTEM_FINGERPRINT_SUFFIX}"

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
                parts.source_fingerprint,
            )
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"palatium:l1:{digest}"

    @classmethod
    def is_cacheable_strategy(cls, strategy: str) -> bool:
        """Only low-risk strategies may populate the L1 response cache."""
        return strategy in LOW_RISK_ROUTE_STRATEGIES or strategy == "clarify"
