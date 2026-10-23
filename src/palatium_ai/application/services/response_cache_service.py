# src/palatium_ai/application/services/response_cache_service.py

"""Application facade for L1 FormatterTaskResult caching (P0.2).

Stores self-contained low-risk exact repeats keyed by tenant + thread + user text +
locale + strategy + source + prior-dialog fingerprints. Live path probes in
formatter_node (W1.2); prior-dependent turns never read or write this layer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.agents.formatter import FormatterTaskResult
from palatium_ai.domain.policies.response_cache import ResponseCacheKeyParts, ResponseCacheKeyPolicy
from palatium_ai.domain.policies.types import ExecutionStrategy

if TYPE_CHECKING:
    from palatium_ai.domain.ports.response_cache import ResponseCachePort

logger = get_logger(__name__)


class ResponseCacheService:
    """Lookup / store low-risk turn results under tenant+thread-keyed L1 hashes."""

    def __init__(
        self,
        port: ResponseCachePort | None,
        *,
        ttl_seconds: int = 3_600,
        enabled: bool = True,
    ) -> None:
        self._port = port
        self._ttl_seconds = max(0, ttl_seconds)
        self._enabled = enabled and port is not None and self._ttl_seconds > 0

    @property
    def enabled(self) -> bool:
        return self._enabled

    def _key_parts(
        self,
        *,
        tenant_key: str,
        thread_key: str,
        user_text: str,
        locale: str,
        strategy: ExecutionStrategy | str,
        source_content: str,
        prior_fingerprint: str,
    ) -> ResponseCacheKeyParts | None:
        if not ResponseCacheKeyPolicy.is_cacheable_strategy(str(strategy)):
            return None
        user_norm = ResponseCacheKeyPolicy.normalize_user_text(user_text)
        if not user_norm:
            return None
        return ResponseCacheKeyParts(
            tenant_key=tenant_key.strip() or "anon",
            thread_key=thread_key.strip() or "none",
            model=f"strategy:{strategy}",
            system_fingerprint=ResponseCacheKeyPolicy.system_fingerprint_for(str(strategy)),
            user_norm=user_norm,
            strategy=strategy,  # type: ignore[arg-type]  # gated by is_cacheable_strategy (017)
            locale=(locale or "und").strip()[:16] or "und",
            source_fingerprint=ResponseCacheKeyPolicy.fingerprint_source(source_content),
            prior_fingerprint=prior_fingerprint or "none",
        )

    async def get(
        self,
        *,
        tenant_key: str,
        thread_key: str,
        user_text: str,
        locale: str,
        strategy: ExecutionStrategy | str,
        source_content: str = "",
        prior_fingerprint: str = "none",
    ) -> FormatterTaskResult | None:
        """Probe L1 for an exact repeat of a self-contained cacheable turn."""
        if not self._enabled or self._port is None:
            return None
        parts = self._key_parts(
            tenant_key=tenant_key,
            thread_key=thread_key,
            user_text=user_text,
            locale=locale,
            strategy=strategy,
            source_content=source_content,
            prior_fingerprint=prior_fingerprint,
        )
        if parts is None:
            return None
        key = ResponseCacheKeyPolicy.build_key(parts)
        raw = await self._port.get(key)
        if raw is None:
            return None
        try:
            result = FormatterTaskResult.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001  # a corrupt cache entry is treated as a miss (080)
            logger.warning("response_cache.decode_failed", error=str(exc))
            return None
        logger.info(
            "response_cache.hit",
            strategy=str(strategy),
            thread_key=thread_key,
            key_suffix=key[-12:],
            user_text=user_text[:50],
        )
        return result

    async def put_if_cacheable(
        self,
        *,
        tenant_key: str,
        thread_key: str,
        user_text: str,
        locale: str,
        strategy: ExecutionStrategy | str,
        result: FormatterTaskResult,
        source_content: str = "",
        prior_fingerprint: str = "none",
        continuation_kind: str | None = None,
        trust_prior_for_workers: bool = False,
        has_turn_attachments: bool = False,
    ) -> None:
        """Store successful self-contained low-risk results for exact repeats."""
        if not self._enabled or self._port is None:
            return
        if result.status == "failure":
            return
        if result.hitl_cards:
            # A card is one-shot server-side: a replayed cached answer would show a
            # card that can never be resolved, so a turn that mints one is not cacheable.
            return
        if not ResponseCacheKeyPolicy.is_turn_cacheable(
            strategy=str(strategy),
            continuation_kind=continuation_kind,
            trust_prior_for_workers=trust_prior_for_workers,
            has_turn_attachments=has_turn_attachments,
        ):
            return
        parts = self._key_parts(
            tenant_key=tenant_key,
            thread_key=thread_key,
            user_text=user_text,
            locale=locale,
            strategy=strategy,
            source_content=source_content,
            prior_fingerprint=prior_fingerprint,
        )
        if parts is None:
            return
        key = ResponseCacheKeyPolicy.build_key(parts)
        await self._port.set(key, result.model_dump_json(), ttl_seconds=self._ttl_seconds)
        logger.debug("response_cache.stored", strategy=str(strategy), key_suffix=key[-12:])
