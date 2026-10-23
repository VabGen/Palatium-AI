"""Merge duplicate ``:MemoryFact`` rows that share one ``node_id`` (M5 audit F6).

``node_id`` is deterministic from ``(user_id, entry_key, version)`` and the write path
used ``CREATE``, so two promoters that both read "not promoted" could commit the same
version twice. The uniqueness constraint now prevents new duplicates, but it cannot be
created while legacy ones exist — this script removes them.

Dry-run by default: the merge deletes graph nodes, which is history-affecting, so it
only runs with ``--execute`` and never at startup (a boot-time delete would be a worse
failure than the duplicate). The earliest node wins; ``SUPERSEDES`` edges of the removed
copies are re-pointed at it so a supersede chain is not truncated.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import get_logger

logger = get_logger(__name__)

_DUPLICATES_CYPHER = """
MATCH (f:MemoryFact)
WITH f.node_id AS node_id, collect({id: elementId(f), created: f.created_at}) AS nodes
WHERE node_id IS NOT NULL AND size(nodes) > 1
RETURN node_id AS node_id, nodes AS nodes
ORDER BY node_id
""".strip()

_MERGE_CYPHER = """
MATCH (keep:MemoryFact) WHERE elementId(keep) = $keep_id
MATCH (dupe:MemoryFact) WHERE elementId(dupe) = $dupe_id
OPTIONAL MATCH (dupe)-[:SUPERSEDES]->(target:MemoryFact)
WHERE elementId(target) <> $keep_id
FOREACH (_ IN CASE WHEN target IS NULL THEN [] ELSE [1] END | MERGE (keep)-[:SUPERSEDES]->(target))
SET keep.superseded_by = coalesce(keep.superseded_by, dupe.superseded_by)
DETACH DELETE dupe
RETURN keep.node_id AS node_id
""".strip()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge :MemoryFact rows sharing one node_id. Dry-run by default.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually merge duplicates. Without this flag the script only lists them.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=500,
        help="Maximum duplicate groups to report/merge in one run (default: 500).",
    )
    return parser


def _created_key(node: dict[str, object]) -> str:
    """Sort key: missing ``created_at`` last, ISO strings compare chronologically."""
    created = node.get("created")
    return str(created) if created is not None else "9999"


async def _run(*, execute: bool, limit: int) -> int:
    settings = get_settings()
    if settings.memory.graph_query_backend != "neo4j":
        logger.error(
            "dedupe.requires_neo4j_backend",
            backend=settings.memory.graph_query_backend,
            hint="set GRAPH_QUERY_BACKEND=neo4j; in-memory graph cannot hold duplicates",
        )
        return 2
    password = (
        settings.memory.graphiti_neo4j_password.get_secret_value() if settings.memory.graphiti_neo4j_password is not None else ""
    )
    if not password.strip():
        logger.error("dedupe.missing_neo4j_password", hint="set GRAPHITI_NEO4J_PASSWORD")
        return 2

    from neo4j import AsyncGraphDatabase  # pyright: ignore[reportMissingImports]

    driver = AsyncGraphDatabase.driver(
        settings.memory.graphiti_neo4j_uri,
        auth=(settings.memory.graphiti_neo4j_user, password),
    )
    groups = 0
    removed = 0
    try:
        result = await driver.execute_query(_DUPLICATES_CYPHER)
        for record in list(result.records)[: max(1, limit)]:
            nodes = sorted(record["nodes"], key=_created_key)
            keep = str(nodes[0]["id"])
            dupes = [str(node["id"]) for node in nodes[1:]]
            groups += 1
            logger.info(
                "dedupe.group",
                node_id=record["node_id"],
                copies=len(nodes),
                keep=keep,
                remove=len(dupes),
                execute=execute,
            )
            if not execute:
                removed += len(dupes)
                continue
            for dupe in dupes:
                await driver.execute_query(_MERGE_CYPHER, keep_id=keep, dupe_id=dupe)
                removed += 1
    finally:
        await driver.close()

    logger.info("dedupe.done", groups=groups, nodes_removed=removed, execute=execute)
    if not execute and groups:
        logger.info("dedupe.dry_run_hint", hint="re-run with --execute to merge")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    return asyncio.run(_run(execute=bool(args.execute), limit=int(args.limit)))


if __name__ == "__main__":
    sys.exit(main())
