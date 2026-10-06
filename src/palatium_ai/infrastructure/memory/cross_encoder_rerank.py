# src/palatium_ai/infrastructure/memory/cross_encoder_rerank.py

"""Optional cross-encoder rerank over MemoryPort hits (Wave M8, eval-gated)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.types.coerce import coerce_float

if TYPE_CHECKING:
    from palatium_ai.domain.memory.ports import MemoryPort
    from palatium_ai.domain.memory.promotion import PromotionCandidate
    from palatium_ai.domain.ports.cross_encoder import CrossEncoderPort


class CrossEncoderRerankMemoryPort:
    """Decorator: over-fetch lexical hits, rerank with CrossEncoderPort scores."""

    def __init__(
        self,
        inner: MemoryPort,
        cross_encoder: CrossEncoderPort,
        *,
        overfetch: int = 3,
    ) -> None:
        self._inner = inner
        self._cross_encoder = cross_encoder
        self._overfetch = max(2, overfetch)

    async def put(self, *, namespace: tuple[str, ...], key: str, value: dict[str, object]) -> None:
        await self._inner.put(namespace=namespace, key=key, value=value)

    async def get(self, *, namespace: tuple[str, ...], key: str) -> dict[str, object] | None:
        return await self._inner.get(namespace=namespace, key=key)

    async def search(
        self,
        *,
        namespace: tuple[str, ...],
        query: str,
        limit: int = 8,
    ) -> list[dict[str, object]]:
        safe_limit = max(1, min(limit, 32))
        candidates = await self._inner.search(
            namespace=namespace,
            query=query,
            limit=min(32, safe_limit * self._overfetch),
        )
        if len(candidates) <= 1:
            return candidates[:safe_limit]
        passages = [str(item.get("text", "")).strip() for item in candidates]
        try:
            scores = await self._cross_encoder.score_pairs(query=query.strip(), passages=passages)
        except Exception:
            return candidates[:safe_limit]
        if len(scores) != len(candidates):
            return candidates[:safe_limit]
        scored: list[tuple[float, dict[str, object]]] = []
        for item, ce_score in zip(candidates, scores, strict=True):
            lexical = coerce_float(item.get("_score", 0.0) or 0.0)
            hybrid = 0.8 * float(ce_score) + 0.2 * _normalize_lexical(lexical)
            enriched = dict(item)
            enriched["_score"] = round(hybrid, 4)
            enriched["_ce"] = round(float(ce_score), 4)
            scored.append((hybrid, enriched))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in scored[:safe_limit]]

    async def forget(self, *, namespace: tuple[str, ...], key: str) -> bool:
        return await self._inner.forget(namespace=namespace, key=key)

    async def bump_access(self, *, namespace: tuple[str, ...], key: str) -> int:
        bump = getattr(self._inner, "bump_access", None)
        if bump is None:
            return 0
        return int(await bump(namespace=namespace, key=key))

    async def list_promotion_candidates(
        self,
        *,
        user_id: str,
        min_access_frequency: int,
        min_importance: float,
        limit: int = 32,
    ) -> list[PromotionCandidate]:
        listing = getattr(self._inner, "list_promotion_candidates", None)
        if listing is None:
            return []
        return list(
            await listing(
                user_id=user_id,
                min_access_frequency=min_access_frequency,
                min_importance=min_importance,
                limit=limit,
            )
        )

    async def mark_promoted(self, *, namespace: tuple[str, ...], key: str) -> bool:
        mark = getattr(self._inner, "mark_promoted", None)
        if mark is None:
            return False
        return bool(await mark(namespace=namespace, key=key))


def _normalize_lexical(score: float) -> float:
    if score <= 0:
        return 0.0
    return min(1.0, score / (score + 1.0))
