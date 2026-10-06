# src/palatium_ai/jobs/retention.py

"""CLI entry: ``python -m palatium_ai.jobs.retention`` (ADR 0002).

Dry-run by default. Destructive execute requires ``--execute`` or
``RETENTION_EXECUTE=true``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from typing import TYPE_CHECKING

from palatium_ai.application.services.retention import (
    RetentionOrchestrator,
    retention_windows_from_settings,
)
from palatium_ai.application.services.retention.orchestrator import RetentionRunResult
from palatium_ai.core.config import get_settings
from palatium_ai.core.logging import get_logger
from palatium_ai.domain.attachments.policies import AttachmentIntakePolicy, AttachmentLimits
from palatium_ai.domain.policies.retention import ALL_RETENTION_CLASSES, RetentionClass, RetentionWindows
from palatium_ai.domain.ports.retention import RetentionClassHandler
from palatium_ai.infrastructure.blob.factory import build_blob_store
from palatium_ai.infrastructure.database.runtime import create_session_factory
from palatium_ai.infrastructure.retention import (
    AttachmentRetentionHandler,
    CheckpointerRetentionHandler,
    KnowledgeOrphanRetentionHandler,
    MemoryRetentionHandler,
    SessionTranscriptRetentionHandler,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from palatium_ai.core.config.settings import Settings
    from palatium_ai.domain.ports.blob_store import BlobStorePort

logger = get_logger(__name__)

EXIT_SUCCESS = 0
EXIT_INVALID_CONFIG = 2
EXIT_RUNTIME_ERROR = 3

_MEMORY_CLASSES: tuple[RetentionClass, ...] = ("memory_medium", "memory_episode", "memory_pii")
_ATTACHMENT_CLASSES: tuple[RetentionClass, ...] = (
    "attachment_attach",
    "attachment_index",
    "attachment_pii",
)
_DB_CLASSES: frozenset[RetentionClass] = frozenset(
    {
        "session_transcript",
        "checkpointer",
        "knowledge_orphan",
        *_MEMORY_CLASSES,
        *_ATTACHMENT_CLASSES,
    }
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Global retention orchestrator. Dry-run by default.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply dispositions (default: plan/report only).",
    )
    parser.add_argument(
        "--class",
        dest="retention_class",
        action="append",
        choices=list(ALL_RETENTION_CLASSES),
        help="Limit to one or more RetentionClass values (repeatable).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override RETENTION_BATCH_SIZE for this run.",
    )
    parser.add_argument(
        "--list-classes",
        action="store_true",
        help="Print RetentionClass identifiers and exit.",
    )
    return parser


def _emit(message: str, *, error: bool = False) -> None:
    """CLI operator output (CronJob logs); not application structlog."""
    stream = sys.stderr if error else sys.stdout
    print(message, file=stream)  # intentional CLI stdout/stderr for operators


def _attachment_limits(settings: Settings) -> AttachmentLimits:
    cfg = settings.attachments
    return AttachmentLimits(
        max_size_bytes=cfg.max_size_bytes,
        max_chunk_bytes=cfg.max_chunk_bytes,
        max_attachments_per_turn=cfg.max_attachments_per_turn,
        max_filename_chars=cfg.max_filename_chars,
        presigned_url_ttl_seconds=cfg.presigned_url_ttl_seconds,
        attach_ttl_seconds=cfg.attach_ttl_seconds,
        index_retention_days=cfg.index_retention_days,
        retention_sweep_batch=cfg.sweep_batch_size,
    )


def _handlers_for(
    session_factory: async_sessionmaker[AsyncSession],
    windows: RetentionWindows,
    *,
    blob_store: BlobStorePort,
    settings: Settings,
) -> dict[RetentionClass, RetentionClassHandler]:
    limits = _attachment_limits(settings)
    handlers: dict[RetentionClass, RetentionClassHandler] = {
        "session_transcript": SessionTranscriptRetentionHandler(session_factory, windows=windows),
        "checkpointer": CheckpointerRetentionHandler(session_factory, windows=windows),
        "knowledge_orphan": KnowledgeOrphanRetentionHandler(session_factory, windows=windows),
    }
    for memory_class in _MEMORY_CLASSES:
        handlers[memory_class] = MemoryRetentionHandler(
            session_factory,
            retention_class=memory_class,
            windows=windows,
        )
    for attachment_class in _ATTACHMENT_CLASSES:
        handlers[attachment_class] = AttachmentRetentionHandler(
            session_factory,
            retention_class=attachment_class,
            windows=windows,
            blob_store=blob_store,
            pending_ttl_seconds=limits.presigned_url_ttl_seconds,
            max_chunk_part_index=AttachmentIntakePolicy.max_chunk_part_index(limits),
        )
    return handlers


async def _async_main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.list_classes:
        for name in ALL_RETENTION_CLASSES:
            _emit(name)
        return EXIT_SUCCESS

    settings = get_settings()
    windows = retention_windows_from_settings(settings)
    if args.batch_size is not None:
        if args.batch_size < 1:
            parser.error("--batch-size must be >= 1")
        windows = windows.model_copy(update={"batch_size": args.batch_size})

    dry_run = not (args.execute or settings.retention.execute)
    classes: tuple[RetentionClass, ...] | None = None
    if args.retention_class:
        classes = tuple(args.retention_class)  # type: ignore[arg-type]

    needs_db = classes is None or any(name in _DB_CLASSES for name in (classes or ()))
    result: RetentionRunResult
    if not needs_db:
        orchestrator = RetentionOrchestrator(windows=windows)
        result = await orchestrator.run(classes=classes, dry_run=dry_run)
    else:
        engine, session_factory = create_session_factory(settings)
        blob_store = build_blob_store(settings)
        try:
            orchestrator = RetentionOrchestrator(
                windows=windows,
                handlers=_handlers_for(session_factory, windows, blob_store=blob_store, settings=settings),
            )
            result = await orchestrator.run(classes=classes, dry_run=dry_run)
        except (OSError, RuntimeError, ValueError) as exc:
            logger.error("retention.job_failed", error=str(exc))
            _emit(f"[ERROR] retention job failed: {exc}", error=True)
            return EXIT_RUNTIME_ERROR
        finally:
            await engine.dispose()

    mode = "dry-run" if result.dry_run else "execute"
    _emit(f"retention job ({mode})")
    _emit(f"  classes: {len(result.reports)}")
    for report in result.reports:
        detail = f" ({report.detail})" if report.detail else ""
        _emit(
            f"  - {report.retention_class}: action={report.action} "
            f"candidates={report.candidates} acted={report.acted} "
            f"held={report.held} failed={report.failed}{detail}"
        )
    return EXIT_SUCCESS


def main(argv: list[str] | None = None) -> int:
    """Sync CLI wrapper for CronJob / compose one-shot."""
    return asyncio.run(_async_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
