# src/palatium_ai/application/services/response_cache_service.py

"""Application facade for L1 FormatterTaskResult caching (P0.2).

Stores low-risk exact-repeat results keyed by tenant + user text + locale +
strategy + source fingerprint. Live path probes in formatter_node (W1.2).
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
    """Lookup / store low-risk turn results under tenant-keyed L1 hashes."""

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
        user_text: str,
        locale: str,
        strategy: ExecutionStrategy | str,
        source_content: str,
    ) -> ResponseCacheKeyParts | None:
        if not ResponseCacheKeyPolicy.is_cacheable_strategy(str(strategy)):
            return None
        user_norm = ResponseCacheKeyPolicy.normalize_user_text(user_text)
        if not user_norm:
            return None
        return ResponseCacheKeyParts(
            tenant_key=tenant_key.strip() or "anon",
            model=f"strategy:{strategy}",
            system_fingerprint=ResponseCacheKeyPolicy.system_fingerprint_for(str(strategy)),
            user_norm=user_norm,
            strategy=strategy,  # type: ignore[arg-type]  # gated by is_cacheable_strategy (017)
            locale=(locale or "und").strip()[:16] or "und",
            source_fingerprint=ResponseCacheKeyPolicy.fingerprint_source(source_content),
        )

    async def get(
        self,
        *,
        tenant_key: str,
        user_text: str,
        locale: str,
        strategy: ExecutionStrategy | str,
        source_content: str = "",
    ) -> FormatterTaskResult | None:
        """Probe L1 for an exact-repeat of a cacheable strategy."""
        if not self._enabled or self._port is None:
            return None
        parts = self._key_parts(
            tenant_key=tenant_key,
            user_text=user_text,
            locale=locale,
            strategy=strategy,
            source_content=source_content,
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
            key_suffix=key[-12:],
            user_text=user_text[:50],
        )
        return result

    async def put_if_cacheable(
        self,
        *,
        tenant_key: str,
        user_text: str,
        locale: str,
        strategy: ExecutionStrategy | str,
        result: FormatterTaskResult,
        source_content: str = "",
    ) -> None:
        """Store successful low-risk results for exact repeats."""
        if not self._enabled or self._port is None:
            return
        if result.status == "failure":
            return
        parts = self._key_parts(
            tenant_key=tenant_key,
            user_text=user_text,
            locale=locale,
            strategy=strategy,
            source_content=source_content,
        )
        if parts is None:
            return
        key = ResponseCacheKeyPolicy.build_key(parts)
        await self._port.set(key, result.model_dump_json(), ttl_seconds=self._ttl_seconds)
        logger.debug("response_cache.stored", strategy=str(strategy), key_suffix=key[-12:])
