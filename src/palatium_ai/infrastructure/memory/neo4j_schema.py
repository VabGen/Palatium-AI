# src/palatium_ai/infrastructure/graph/neo4j_schema.py

"""Runtime schema bootstrap for MemoryFact (Phase 4; Alembic не используется)."""

from __future__ import annotations

from typing import TYPE_CHECKING, LiteralString

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.graph.temporal import EXPIRED_AT_SENTINEL

if TYPE_CHECKING:
    from neo4j import AsyncDriver  # pyright: ignore[reportMissingImports]

logger = get_logger(__name__)

_SENTINEL = EXPIRED_AT_SENTINEL
_BATCH = 5000

_INDEX_STATEMENTS: tuple[LiteralString, ...] = (
    "CREATE INDEX memory_fact_expiry IF NOT EXISTS FOR (f:MemoryFact) ON (f.expired_at)",
    "CREATE INDEX memory_fact_user_thread IF NOT EXISTS FOR (f:MemoryFact) ON (f.user_id, f.thread_id, f.valid_at, f.invalid_at)",
)

# One node per (identity, version). ``node_id`` is deterministic, so identical ids mean
# the same fact version — the second writer must hit an error, not create a twin active
# fact (M5 audit F6). Creation fails while legacy duplicates exist; that is reported
# loudly by name and fixed by ``scripts/dedupe_memory_facts.py`` (operator-run, not
# startup: silently deleting graph history during boot is a worse failure).
_CONSTRAINT_STATEMENTS: tuple[LiteralString, ...] = (
    "CREATE CONSTRAINT memory_fact_node_id IF NOT EXISTS FOR (f:MemoryFact) REQUIRE f.node_id IS UNIQUE",
)


async def ensure_memory_schema(driver: AsyncDriver) -> int:
    """Идемпотентно: backfill expired_at батчами + индексы. Не роняет startup."""
    backfilled = 0
    try:
        while True:
            result = await driver.execute_query(
                "MATCH (f:MemoryFact) WHERE f.expired_at IS NULL "
                "WITH f LIMIT $batch SET f.expired_at = datetime($sentinel) "
                "RETURN count(f) AS n",
                batch=_BATCH,
                sentinel=_SENTINEL,
            )
            n = int(result.records[0]["n"]) if result.records else 0
            backfilled += n
            if n < _BATCH:
                break
    except Exception as e:  # noqa: BLE001  # backfill is best-effort; index creation still runs (060)
        logger.warning("neo4j.schema_bootstrap.backfill_failed", error=str(e))

    for statement in _INDEX_STATEMENTS:
        try:
            await driver.execute_query(statement)
        except Exception as e:  # noqa: BLE001  # per-statement index creation is best-effort (060)
            logger.warning(
                "neo4j.schema_bootstrap.index_failed",
                statement=statement[:80],
                error=str(e),
            )

    for statement in _CONSTRAINT_STATEMENTS:
        try:
            await driver.execute_query(statement)
        except Exception as e:  # noqa: BLE001  # constraint creation must not abort startup (060)
            # Not "best-effort" in the "nobody cares" sense: the uniqueness guarantee is
            # what stops concurrent promote from writing one fact version twice, so the
            # log names the likely cause and the fix instead of hiding it at debug level.
            logger.warning(
                "neo4j.schema_bootstrap.constraint_failed",
                statement=statement[:80],
                error=str(e),
                hint="duplicate :MemoryFact rows likely exist; run scripts/dedupe_memory_facts.py --execute",
            )

    logger.info("neo4j.schema_bootstrap", backfilled=backfilled)
    return backfilled
