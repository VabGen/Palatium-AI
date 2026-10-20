# src/palatium_ai/jobs/memory_promotion_factory.py

"""Composition for memory jobs: promote service over Postgres + graph ports (060).

Lives in ``jobs/`` because it imports ``infrastructure``: the application layer is
only allowed to depend on domain ports (000). Both the one-shot promote CLI and the
scheduled consolidation pass use it, so eval-gated flags cannot drift between them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from sqlalchemy import text

from palatium_ai.application.services.memory_promotion import MemoryPromotionService
from palatium_ai.domain.memory.promotion import PromotionThresholds
from palatium_ai.infrastructure.graph.factory import build_graph_write_port
from palatium_ai.infrastructure.memory.postgres_memory_port import PostgresMemoryPort

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.core.config.settings import Settings

# Hard ceiling for one discovery RPC; the job still applies the per-user batch limit.
_MAX_OWNER_IDS = 10_000


def build_memory_promotion_service(
    *,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> MemoryPromotionService:
    """Build the batch promote service from application settings."""
    return MemoryPromotionService(
        memory=PostgresMemoryPort(session_factory),
        graph_write=build_graph_write_port(settings),
        thresholds=PromotionThresholds(
            min_access_frequency=settings.memory.promote_min_access_frequency,
            min_importance=settings.memory.promote_min_importance,
        ),
        xmemory_decouple=settings.memory.xmemory_decouple,
        bayesian_trust=settings.memory.bayesian_trust,
        hebbian_edge_bump=settings.memory.hebbian_edge_bump,
    )


async def list_promotion_owner_ids(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    min_importance: float,
    limit: int = _MAX_OWNER_IDS,
) -> list[str]:
    """Enumerate RLS owners with promotable rows via SECURITY DEFINER (060).

    A plain ``SELECT DISTINCT user_id`` cannot see other tenants under FORCE RLS,
    so the CronJob would silently promote nobody. The RPC is the privileged,
    narrow reading path — same pattern as ``memory.retention_*`` (ADR 0002).
    """
    safe_limit = max(1, min(int(limit), _MAX_OWNER_IDS))
    async with session_factory() as session:
        result = await session.execute(
            text("SELECT memory.promotion_owner_ids(:min_importance, :limit)"),
            {"min_importance": min_importance, "limit": safe_limit},
        )
        return [str(user_id) for user_id in result.scalars().all() if user_id]


async def resolve_promotion_user_ids(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    explicit: Sequence[str],
    all_users: bool,
    min_importance: float,
) -> list[str]:
    """Merge operator-provided scopes with optional RPC discovery (stable order)."""
    resolved = [user_id.strip() for user_id in explicit if user_id.strip()]
    if all_users:
        resolved.extend(
            await list_promotion_owner_ids(
                session_factory,
                min_importance=min_importance,
            )
        )
    return list(dict.fromkeys(resolved))
