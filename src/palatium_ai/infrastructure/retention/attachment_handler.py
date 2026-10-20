# src/palatium_ai/infrastructure/retention/attachment_handler.py

"""Global attachment reclaim via SECURITY DEFINER + blob store (FORCE RLS safe)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import text

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.attachments.policies import DEFAULT_ATTACHMENT_LIMITS, AttachmentIntakePolicy
from palatium_ai.domain.policies.retention import RetentionClass, RetentionPolicy, RetentionWindows
from palatium_ai.domain.ports.retention import RetentionClassReport
from palatium_ai.infrastructure.retention._scalars import rpc_int

if TYPE_CHECKING:
    from sqlalchemy.engine import RowMapping
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.domain.ports.blob_store import BlobStorePort

logger = get_logger(__name__)


def _row_to_dict(row: RowMapping) -> dict[str, object]:
    """Map one RPC row onto the purge contract shared by both candidate queries."""
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "blob_key": row["blob_key"],
        "derived_text_key": row["derived_text_key"],
        "mode": row["mode"],
        "status": row["status"],
        "project_id": row["project_id"],
        "contains_pii": bool(row["contains_pii"]),
        "expires_at": row["expires_at"],
        "created_at": row["created_at"],
    }


def _created_at(row: dict[str, object]) -> datetime:
    value = row.get("created_at")
    return value if isinstance(value, datetime) else datetime.min.replace(tzinfo=UTC)


def _merge_unique(
    primary: list[dict[str, object]],
    extra: list[dict[str, object]],
    *,
    limit: int,
) -> list[dict[str, object]]:
    """Union two bounded candidate sets, oldest first, without spending a slot twice."""
    merged: list[dict[str, object]] = []
    seen: set[object] = set()
    for row in (*primary, *extra):
        key = row.get("id")
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    merged.sort(key=_created_at)
    return merged[:limit]


class AttachmentRetentionHandler:
    """Reclaim expired/stale-pending attachments cross-tenant (ADR 0002 / W3)."""

    _retention_class: RetentionClass

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        retention_class: RetentionClass,
        windows: RetentionWindows,
        blob_store: BlobStorePort,
        pending_ttl_seconds: int,
        max_chunk_part_index: int | None = None,
        orphan_grace_seconds: int = DEFAULT_ATTACHMENT_LIMITS.orphan_grace_seconds,
    ) -> None:
        # ``in`` against a str-container widens Literal→str under basedpyright;
        # match keeps the RetentionClass pin.
        match retention_class:
            case "attachment_attach" | "attachment_index" | "attachment_pii":
                self._retention_class = retention_class
            case _:
                msg = f"unsupported attachment retention class: {retention_class}"
                raise ValueError(msg)
        self._session_factory = session_factory
        self._windows = windows
        self._blob_store = blob_store
        self._pending_ttl_seconds = max(1, pending_ttl_seconds)
        self._orphan_grace_seconds = max(1, orphan_grace_seconds)
        self._max_chunk_part_index = (
            max_chunk_part_index
            if max_chunk_part_index is not None
            else AttachmentIntakePolicy.max_chunk_part_index(DEFAULT_ATTACHMENT_LIMITS)
        )

    @property
    def retention_class(self) -> RetentionClass:
        return self._retention_class

    async def plan(self, *, limit: int) -> RetentionClassReport:
        now = datetime.now(UTC)
        pending_before = now - timedelta(seconds=self._pending_ttl_seconds)
        orphan_before = now - timedelta(seconds=self._orphan_grace_seconds)
        async with self._session_factory() as session:
            expired = await self._count(session, now=now, pending_before=pending_before)
            orphans = await self._count_orphans(session, orphan_before=orphan_before)
        decision = RetentionPolicy.decide(self.retention_class)
        return RetentionClassReport(
            retention_class=self.retention_class,
            action=decision.action,
            # Per-rule counts: a row can match both predicates, so this is an upper
            # bound. ``execute`` reports the deduplicated batch it actually acted on.
            candidates=expired + orphans,
            detail=(
                f"batch_cap={limit};expired={expired};orphans={orphans};"
                f"pending_before={pending_before.isoformat()};"
                f"orphan_before={orphan_before.isoformat()}"
            ),
        )

    async def execute(self, *, limit: int) -> RetentionClassReport:
        now = datetime.now(UTC)
        pending_before = now - timedelta(seconds=self._pending_ttl_seconds)
        orphan_before = now - timedelta(seconds=self._orphan_grace_seconds)
        batch = max(1, min(limit, self._windows.batch_size))
        decision = RetentionPolicy.decide(self.retention_class)
        async with self._session_factory() as session:
            rows = await self._list(
                session,
                now=now,
                pending_before=pending_before,
                limit=batch,
            )
            orphan_rows = await self._list_orphans(
                session,
                orphan_before=orphan_before,
                limit=batch,
            )
        # Both predicates can name the same row (expired TTL *and* thread-less);
        # collapse by id before spending the bounded batch on it twice (080).
        rows = _merge_unique(rows, orphan_rows, limit=batch)
        purged = 0
        failed = 0
        knowledge_docs = 0
        for row in rows:
            try:
                docs = await self._purge_one(row)
            except (OSError, RuntimeError, ValueError) as exc:
                failed += 1
                logger.warning(
                    "retention.attachment_purge_failed",
                    attachment_id=str(row["id"]),
                    retention_class=self.retention_class,
                    error=str(exc),
                )
                continue
            purged += 1
            knowledge_docs += docs
        return RetentionClassReport(
            retention_class=self.retention_class,
            action=decision.action if decision.action != "anonymize" else "delete",
            candidates=len(rows),
            acted=purged,
            failed=failed,
            detail=(
                f"knowledge_docs={knowledge_docs};pending_before={pending_before.isoformat()};"
                f"orphan_before={orphan_before.isoformat()}"
            ),
        )

    async def _count(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        pending_before: datetime,
    ) -> int:
        result = await session.execute(
            text(
                """
                SELECT palatium_ai.retention_count_reclaimable_attachments(
                  :now, :pending_before, :cls
                )
                """
            ),
            {"now": now, "pending_before": pending_before, "cls": self.retention_class},
        )
        return rpc_int(result.scalar_one())

    async def _count_orphans(
        self,
        session: AsyncSession,
        *,
        orphan_before: datetime,
    ) -> int:
        """Thread-less attach rows that no read path can ever bind (020)."""
        result = await session.execute(
            text(
                """
                SELECT palatium_ai.retention_count_orphan_attachments(
                  :orphan_before, :cls
                )
                """
            ),
            {"orphan_before": orphan_before, "cls": self.retention_class},
        )
        return rpc_int(result.scalar_one())

    async def _list(
        self,
        session: AsyncSession,
        *,
        now: datetime,
        pending_before: datetime,
        limit: int,
    ) -> list[dict[str, object]]:
        result = await session.execute(
            text(
                """
                SELECT id, user_id, blob_key, derived_text_key, mode, status,
                       project_id, contains_pii, expires_at, created_at
                FROM palatium_ai.retention_list_reclaimable_attachments(
                  :now, :pending_before, :lim, :cls
                )
                """
            ),
            {
                "now": now,
                "pending_before": pending_before,
                "lim": limit,
                "cls": self.retention_class,
            },
        )
        return [_row_to_dict(row) for row in result.mappings().all()]

    async def _list_orphans(
        self,
        session: AsyncSession,
        *,
        orphan_before: datetime,
        limit: int,
    ) -> list[dict[str, object]]:
        result = await session.execute(
            text(
                """
                SELECT id, user_id, blob_key, derived_text_key, mode, status,
                       project_id, contains_pii, expires_at, created_at
                FROM palatium_ai.retention_list_orphan_attachments(
                  :orphan_before, :lim, :cls
                )
                """
            ),
            {
                "orphan_before": orphan_before,
                "lim": limit,
                "cls": self.retention_class,
            },
        )
        return [_row_to_dict(row) for row in result.mappings().all()]

    async def _purge_one(self, row: dict[str, object]) -> int:
        attachment_id = row["id"]
        if not isinstance(attachment_id, UUID):
            attachment_id = UUID(str(attachment_id))
        blob_key = str(row["blob_key"])
        derived = row.get("derived_text_key")

        for index in range(self._max_chunk_part_index + 1):
            await self._blob_store.delete(AttachmentIntakePolicy.chunk_part_key(attachment_id, index))
        await self._blob_store.delete(blob_key)
        if derived:
            await self._blob_store.delete(str(derived))

        # Always cascade: attach-mode rows should not have knowledge, but index
        # ingest uses source_document_id = attachment id / project:<id>:<hex>.
        async with self._session_factory() as session:
            knowledge_result = await session.execute(
                text("SELECT knowledge.retention_delete_by_attachment(:id)"),
                {"id": attachment_id},
            )
            knowledge_deleted = rpc_int(knowledge_result.scalar_one())
            deleted = await session.execute(
                text("SELECT palatium_ai.retention_delete_attachment(:id)"),
                {"id": attachment_id},
            )
            if rpc_int(deleted.scalar_one()) < 1:
                await session.rollback()
                msg = f"attachment row missing after blob purge: {attachment_id}"
                raise RuntimeError(msg)
            await session.commit()
        return knowledge_deleted
