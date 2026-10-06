# src/palatium_ai/application/services/attachment_service.py

"""Attachment use-cases: intake -> scan -> parse -> fence -> persist (020, 065).

The service is the only place that combines the intake policy, the security
pipeline and persistence. Two invariants hold across every path:

* the client's declared metadata is never trusted — storage is the authority for
  size, and the row is only moved to a usable state by the pipeline outcome;
* untrusted text reaches a prompt only through :meth:`build_turn_context`, which
  re-scans the stored body and wraps it in the mandatory fence. There is no other
  accessor that returns attachment text.
"""

from __future__ import annotations

import json

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, NoReturn
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from palatium_ai.application.agents.text_ingestor.chunking import chunk_text
from palatium_ai.application.services.attachment_pipeline import AttachmentPipeline
from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.security.prompt_injection import redact_findings, scan_prompt_injection
from palatium_ai.domain.agents.text_ingestor import TextChunk
from palatium_ai.domain.attachments import (
    DEFAULT_ATTACHMENT_LIMITS,
    Attachment,
    AttachmentAnalyzePayload,
    AttachmentChunkedUploadError,
    AttachmentContent,
    AttachmentContentMissingError,
    AttachmentContextBlock,
    AttachmentIndexPayload,
    AttachmentIntakePolicy,
    AttachmentIntakeRejectedError,
    AttachmentLimits,
    AttachmentMode,
    AttachmentModeMismatchError,
    AttachmentNotFoundError,
    AttachmentNotUsableError,
    AttachmentRestoreNotAllowedError,
    AttachmentRestorePayload,
    AttachmentRetentionPolicy,
    AttachmentTurnContext,
    AttachmentUploadTooLargeError,
    IntakeDecision,
)
from palatium_ai.domain.attachments.fence_source import attachment_fence_source
from palatium_ai.domain.mcp.tool_policy import risk_score_for_tier
from palatium_ai.domain.memory.tool_output import wrap_untrusted_tool_output
from palatium_ai.domain.policies.types import UntrustedContentAction
from palatium_ai.domain.policies.untrusted_content import (
    DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
    UntrustedContentPolicy,
    UntrustedContentThresholds,
)
from palatium_ai.domain.ports.blob_store import BlobNotFoundError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redis.asyncio import Redis

    from palatium_ai.application.services.document_ingest_service import DocumentIngestService
    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.hitl.cards import HITLCardView
    from palatium_ai.domain.ports.attachment_analysis import AttachmentAnalysisPort
    from palatium_ai.domain.ports.attachment_connector import AttachmentConnectorPort
    from palatium_ai.domain.ports.attachments import AttachmentRepositoryPort
    from palatium_ai.domain.ports.blob_store import BlobStorePort
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_DERIVED_CONTENT_TYPE = "application/json"
_PENDING_PREFIX = "attachment_index:pending:"
_PENDING_TTL_SECONDS = 5 * 60
_INDEX_TASK_PREFIX = "att-index-"
_RESTORE_TASK_PREFIX = "att-restore-"
_ANALYZE_TASK_PREFIX = "att-analyze-"
_PLATFORM_SERVER = "platform"
_INGEST_TOOL = "ingest_document"
_RESTORE_TOOL = "attachment_quarantine_restore"
_ANALYZE_TOOL = "attachment_analyze"
_RESTORE_PENDING_PREFIX = "attachment_restore:pending:"
_ANALYZE_PENDING_PREFIX = "attachment_analyze:pending:"
_QUARANTINE_RESTORE_REASONS = frozenset({"injection_detected"})
_TABULAR_ANALYZE_MIMES = frozenset(
    {
        "text/csv",
        "text/plain",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
)
# Mirrors the DocumentIngestService default so one document chunks identically
# whichever entry point produced it (050: no divergent chunk sizes by accident).
_INDEX_CHUNK_CHARS = 1500
_USABLE_FOR_TURN = frozenset({"ready", "indexed"})
# States where overwriting the original object is still safe: the pipeline has not
# read it yet, so nothing derived can go stale (020).
_ACCEPTS_UPLOAD = frozenset({"pending", "uploaded"})


class AttachmentUploadTicket(BaseModel):
    """Handed to the client so it can PUT the bytes straight to the blob store."""

    model_config = {"frozen": True}

    attachment_id: UUID
    upload_url: str
    expires_at: datetime


class AttachmentDownloadTicket(BaseModel):
    """Time-boxed download URL for an owned, usable original blob (020).

    Never exposes the storage key — only a short-lived URL and display metadata.
    """

    model_config = {"frozen": True}

    attachment_id: UUID
    download_url: str
    filename: str
    mime_type: str
    expires_at: datetime
    size_bytes: int = Field(ge=0)


class AttachmentComplianceRecord(BaseModel):
    """Metadata-only export for compliance review (no bytes, no derived text)."""

    model_config = {"frozen": True}

    id: UUID
    filename: str
    mime_type: str
    status: str
    rejection_reason: str | None = None
    created_at: datetime
    expires_at: datetime | None = None
    page_count: int | None = None
    size_bytes: int = Field(ge=0)
    contains_pii: bool = False


class AttachmentSweepResult(BaseModel):
    """Outcome of one retention pass over a single owner's expired rows.

    ``skipped`` is not noise: it counts rows the store reported as expired while
    the domain policy disagreed, which is the signal that an adapter drifted.
    """

    model_config = {"frozen": True}

    considered: int = Field(default=0, ge=0)
    purged: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    skipped: int = Field(default=0, ge=0)


class AttachmentService:
    """Use-cases over the attachment aggregate and pipeline."""

    def __init__(
        self,
        *,
        repository: AttachmentRepositoryPort,
        blob_store: BlobStorePort,
        pipeline: AttachmentPipeline,
        hitl_service: HitlService | None = None,
        mcp_registry: MCPRegistryPort | None = None,
        redis_client: Redis | None = None,
        mcp_tool_call_repository: McpToolCallRecorderPort | None = None,
        document_ingest_service: DocumentIngestService | None = None,
        analysis: AttachmentAnalysisPort | None = None,
        connector: AttachmentConnectorPort | None = None,
        limits: AttachmentLimits = DEFAULT_ATTACHMENT_LIMITS,
        thresholds: UntrustedContentThresholds = DEFAULT_UNTRUSTED_CONTENT_THRESHOLDS,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store
        self._pipeline = pipeline
        self._hitl = hitl_service
        self._mcp_registry = mcp_registry
        self._redis = redis_client
        self._mcp_tool_call_repository = mcp_tool_call_repository
        self._document_ingest = document_ingest_service
        self._analysis = analysis
        self._connector = connector
        self._limits = limits
        self._thresholds = thresholds
        self._index_pending: dict[str, AttachmentIndexPayload] = {}
        self._restore_pending: dict[str, AttachmentRestorePayload] = {}
        self._analyze_pending: dict[str, AttachmentAnalyzePayload] = {}
        self._last_analysis: dict[str, object] = {}

    def bind_document_ingest(self, document_ingest: DocumentIngestService) -> None:
        """Late-bind after composition root builds DocumentIngestService (circular DI)."""
        self._document_ingest = document_ingest

    @traceable(name="attachment.init_upload")
    async def init_upload(
        self,
        *,
        user_id: str,
        filename: str,
        mime_type: str,
        size_bytes: int,
        mode: AttachmentMode,
        thread_id: str | None = None,
        expires_in_seconds: int | None = None,
        project_id: str | None = None,
    ) -> AttachmentUploadTicket:
        """Validate intake, create the PENDING row and issue a presigned PUT URL."""
        decision = AttachmentIntakePolicy.validate(
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            limits=self._limits,
        )
        if decision.refused:
            self._raise_intake_refusal(decision)
        if not self._pipeline.supports_media_type(mime_type):
            # The registry knows the MIME but no wired parser can read it (a lean
            # install without the ``attachments`` extra, or a type left in the
            # registry ahead of its parser). Refuse now: accepting the upload only
            # to reject it after the scan/parse round-trip is a contract drift (055).
            self._raise_intake_refusal(
                IntakeDecision(allowed=False, filename=decision.filename, reason="mime_not_allowed")
            )

        scoped_project = (project_id or "").strip() or None
        if scoped_project and mode != "index":
            scoped_project = None

        now = datetime.now(UTC)
        attachment_id = uuid4()
        policy_expiry = AttachmentIntakePolicy.expiry_for(mode, now=now, limits=self._limits)
        expires_at = policy_expiry
        if expires_in_seconds is not None:
            # Client may shorten TTL, never extend past the mode policy ceiling (W6 G16).
            requested = now + timedelta(seconds=expires_in_seconds)
            expires_at = min(requested, policy_expiry)
        attachment = Attachment(
            id=attachment_id,
            user_id=user_id,
            thread_id=thread_id,
            filename=decision.filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            blob_key=AttachmentIntakePolicy.blob_key(attachment_id),
            mode=mode,
            status="pending",
            project_id=scoped_project,
            created_at=now,
            expires_at=expires_at,
        )
        created = await self._create_within_quota(attachment, now=now)
        upload_url = await self._blob_store.presigned_put_url(
            created.blob_key,
            content_type=created.mime_type,
            expires_seconds=self._limits.presigned_url_ttl_seconds,
        )
        await self._audit(
            event="attachment_init",
            thread_id=thread_id or "",
            payload={"attachment_id": str(created.id), "mode": created.mode},
        )
        logger.info("attachment.init", attachment_id=str(created.id), mode=created.mode, thread_id=thread_id or "")
        return AttachmentUploadTicket(
            attachment_id=created.id,
            upload_url=upload_url,
            expires_at=created.expires_at or now,
        )

    @property
    def max_upload_bytes(self) -> int:
        """Cap a caller must enforce while reading a proxied upload body (020)."""
        return self._limits.max_size_bytes

    @property
    def max_chunk_bytes(self) -> int:
        """Per-part cap for resumable ``POST /{id}/chunks/{index}`` uploads."""
        return self._limits.max_chunk_bytes

    @traceable(name="attachment.receive_upload")
    async def receive_upload(
        self,
        *,
        attachment_id: UUID,
        user_id: str,
        data: bytes,
    ) -> Attachment:
        """Store original bytes the API received on the client's behalf.

        The presigned PUT from :meth:`init_upload` is the primary path; this exists
        because the in-process dev store has no HTTP surface of its own, and because
        some deployments keep object storage off the browser's network
        (see ``docs/runbook.md`` §16.4). It is not a bypass: the row must still be
        pre-pipeline, the cap is enforced here as well as in the router, and
        :meth:`complete_upload` re-derives the size from storage, so bytes written
        this way are verified exactly like a presigned PUT.

        Raises:
            AttachmentNotFoundError: the id is unknown or owned by someone else.
            AttachmentNotUsableError: the row already passed the pipeline, so
                overwriting the original would desynchronise it from its derived text.
            AttachmentIntakeRejectedError: the body is empty.
            AttachmentUploadTooLargeError: the body exceeds the configured cap.
        """
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.status not in _ACCEPTS_UPLOAD:
            raise AttachmentNotUsableError(attachment_id, state=attachment.status)
        if not data:
            raise AttachmentIntakeRejectedError("size_invalid", filename=attachment.filename)
        if len(data) > self._limits.max_size_bytes:
            raise AttachmentUploadTooLargeError(
                attachment_id,
                size_bytes=len(data),
                max_size_bytes=self._limits.max_size_bytes,
            )

        await self._blob_store.write_bytes(attachment.blob_key, data, content_type=attachment.mime_type)
        # ``uploaded`` is the honest state: the object is in storage but the pipeline
        # has not run. ``complete_upload`` accepts both, so this stays idempotent.
        saved = await self._repository.save(attachment.model_copy(update={"status": "uploaded"}))
        await self._audit(
            event="attachment_received",
            thread_id=saved.thread_id or "",
            payload={"attachment_id": str(saved.id), "size_bytes": str(len(data))},
        )
        logger.info("attachment.receive_upload", attachment_id=str(saved.id), size_bytes=len(data))
        return saved

    @traceable(name="attachment.put_upload_chunk")
    async def put_upload_chunk(
        self,
        *,
        attachment_id: UUID,
        user_id: str,
        chunk_index: int,
        data: bytes,
    ) -> None:
        """Stage one resumable part under ``chunk_part_key`` (W4 G08)."""
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.status not in _ACCEPTS_UPLOAD:
            raise AttachmentNotUsableError(attachment_id, state=attachment.status)
        max_index = AttachmentIntakePolicy.max_chunk_part_index(self._limits)
        if chunk_index < 0 or chunk_index >= max_index:
            raise AttachmentChunkedUploadError(attachment_id, detail="chunk index out of range")
        if not data:
            raise AttachmentIntakeRejectedError("size_invalid", filename=attachment.filename)
        if len(data) > self._limits.max_chunk_bytes:
            raise AttachmentUploadTooLargeError(
                attachment_id,
                size_bytes=len(data),
                max_size_bytes=self._limits.max_chunk_bytes,
            )
        part_key = AttachmentIntakePolicy.chunk_part_key(attachment_id, chunk_index)
        await self._blob_store.write_bytes(part_key, data, content_type="application/octet-stream")
        logger.info(
            "attachment.put_chunk",
            attachment_id=str(attachment_id),
            chunk_index=chunk_index,
            size_bytes=len(data),
        )

    @traceable(name="attachment.finalize_chunked_upload")
    async def finalize_chunked_upload(
        self,
        *,
        attachment_id: UUID,
        user_id: str,
        chunk_count: int,
    ) -> Attachment:
        """Concatenate staged parts into the original blob key, then mark uploaded."""
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.status not in _ACCEPTS_UPLOAD:
            raise AttachmentNotUsableError(attachment_id, state=attachment.status)
        max_index = AttachmentIntakePolicy.max_chunk_part_index(self._limits)
        if chunk_count <= 0 or chunk_count > max_index:
            raise AttachmentChunkedUploadError(attachment_id, detail="invalid chunk_count")

        parts: list[bytes] = []
        total = 0
        for index in range(chunk_count):
            part_key = AttachmentIntakePolicy.chunk_part_key(attachment_id, index)
            try:
                part = await self._blob_store.read_bytes(part_key)
            except BlobNotFoundError as exc:
                raise AttachmentChunkedUploadError(
                    attachment_id,
                    detail=f"missing staged part {index}",
                ) from exc
            total += len(part)
            if total > self._limits.max_size_bytes:
                raise AttachmentUploadTooLargeError(
                    attachment_id,
                    size_bytes=total,
                    max_size_bytes=self._limits.max_size_bytes,
                )
            parts.append(part)

        assembled = b"".join(parts)
        await self._blob_store.write_bytes(
            attachment.blob_key,
            assembled,
            content_type=attachment.mime_type,
        )
        await self._delete_chunk_parts(attachment_id, up_to_index=chunk_count)
        saved = await self._repository.save(
            attachment.model_copy(update={"status": "uploaded", "size_bytes": len(assembled)})
        )
        await self._audit(
            event="attachment_chunked_finalized",
            thread_id=saved.thread_id or "",
            payload={
                "attachment_id": str(saved.id),
                "chunk_count": str(chunk_count),
                "size_bytes": str(len(assembled)),
            },
        )
        logger.info(
            "attachment.finalize_chunks",
            attachment_id=str(saved.id),
            chunk_count=chunk_count,
            size_bytes=len(assembled),
        )
        return saved

    @traceable(name="attachment.complete_upload")
    async def complete_upload(self, *, attachment_id: UUID, user_id: str) -> Attachment:
        """Confirm the upload and run the scan/parse/injection pipeline exactly once."""
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.status not in ("pending", "uploaded", "scanning"):
            return attachment
        # Persist ``scanning`` so concurrent GET/poll clients see progress (W1 G04)
        # before the long AV/OCR path returns.
        if attachment.status != "scanning":
            attachment = await self._repository.save(attachment.model_copy(update={"status": "scanning"}))

        try:
            outcome = await self._pipeline.run(attachment, limits=self._limits)
        except Exception:
            failed = await self._repository.save(
                attachment.model_copy(
                    update={
                        "status": "rejected",
                        "rejection_reason": "parse_failed",
                        "error": "pipeline failed unexpectedly",
                    },
                ),
            )
            agent_metrics.record_error("attachments", "pipeline_unexpected")
            logger.exception("attachment.complete unexpected failure", attachment_id=str(failed.id))
            return failed

        updated = attachment
        if outcome.content is not None:
            derived_key = AttachmentIntakePolicy.derived_text_key(attachment.id)
            await self._write_content(derived_key, outcome.content)
            updated = attachment.model_copy(update={"derived_text_key": derived_key})
        row_update: dict[str, object] = {
            "status": outcome.status,
            "size_bytes": outcome.stored_size_bytes,
            "rejection_reason": outcome.rejection_reason,
            "error": outcome.error,
            "page_count": outcome.content.page_count if outcome.content is not None else None,
            "contains_pii": outcome.content.contains_pii if outcome.content is not None else False,
        }
        if outcome.detected_mime_type:
            row_update["mime_type"] = outcome.detected_mime_type
        updated = updated.model_copy(update=row_update)
        saved = await self._repository.save(updated)
        await self._audit(
            event="attachment_completed",
            thread_id=saved.thread_id or "",
            payload={
                "attachment_id": str(saved.id),
                "status": saved.status,
                "rejection_reason": saved.rejection_reason or "",
                "page_count": str(saved.page_count or 0),
                "contains_pii": "true" if saved.contains_pii else "false",
            },
        )
        if not outcome.admitted:
            agent_metrics.record_error("attachments", f"pipeline_{outcome.rejection_reason or 'refused'}")
        logger.info(
            "attachment.complete",
            attachment_id=str(saved.id),
            status=saved.status,
            page_count=saved.page_count or 0,
        )
        return saved

    @traceable(name="attachment.issue_download")
    async def issue_download(self, *, attachment_id: UUID, user_id: str) -> AttachmentDownloadTicket:
        """Mint a short-lived GET URL for the original blob (owner + usable only)."""
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.status not in _USABLE_FOR_TURN:
            raise AttachmentNotUsableError(attachment_id, state=attachment.status)
        if attachment.is_expired:
            raise AttachmentNotUsableError(attachment_id, state="expired")
        ttl = self._limits.presigned_url_ttl_seconds
        url = await self._blob_store.presigned_get_url(attachment.blob_key, expires_seconds=ttl)
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl)
        await self._audit(
            event="attachment_download_issued",
            thread_id=attachment.thread_id or "",
            payload={"attachment_id": str(attachment.id)},
        )
        return AttachmentDownloadTicket(
            attachment_id=attachment.id,
            download_url=url,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            expires_at=expires_at,
            size_bytes=attachment.size_bytes,
        )

    @traceable(name="attachment.get")
    async def get(self, *, attachment_id: UUID, user_id: str) -> Attachment:
        """Fetch one attachment or raise the typed not-found error."""
        return await self._require(attachment_id, user_id=user_id)

    async def list_for_thread(self, *, thread_id: str, user_id: str) -> list[Attachment]:
        """List live attachments bound to a thread, newest first.

        Expired rows are reclaimed before the read and filtered out afterwards, so
        the client never sees a file it can no longer use (mirrors the lazy TTL
        close on the HITL queue).
        """
        await self._reclaim_expired(user_id=user_id)
        rows = await self._repository.list_for_thread(thread_id, user_id=user_id)
        return [row for row in rows if not row.is_expired]

    @traceable(name="attachment.sweep_expired")
    async def sweep_expired(
        self,
        *,
        user_id: str,
        now: datetime | None = None,
        limit: int | None = None,
    ) -> AttachmentSweepResult:
        """Reclaim one owner's expired rows and their stored objects (020, 060).

        Scoped to a single ``user_id`` by construction: ``attachments`` is under
        ``FORCE ROW LEVEL SECURITY``, so the app role has no cross-tenant variant
        of this query and retention is enforced per owner.
        """
        reference = now or datetime.now(UTC)
        # An intake that never received its bytes is dead once its presigned ticket
        # expired — it must be reclaimable long before the row's own TTL (080).
        pending_before = reference - timedelta(seconds=self._limits.presigned_url_ttl_seconds)
        batch = self._limits.retention_sweep_batch if limit is None else limit
        candidates = await self._repository.list_reclaimable(
            reference,
            pending_before=pending_before,
            user_id=user_id,
            limit=batch,
        )
        purged = 0
        failed = 0
        skipped = 0
        for attachment in candidates:
            if not self._is_reclaimable(attachment, now=reference):
                # Defence in depth: an overly eager adapter must not delete live data.
                skipped += 1
                continue
            try:
                await self._purge(attachment, user_id=user_id)
            except Exception:
                failed += 1
                agent_metrics.record_error("attachments", "retention_sweep_failed")
                logger.warning("attachment retention purge failed", attachment_id=str(attachment.id))
                continue
            purged += 1
        if candidates:
            logger.info(
                "attachment.retention_sweep",
                considered=len(candidates),
                purged=purged,
                failed=failed,
                skipped=skipped,
            )
        return AttachmentSweepResult(
            considered=len(candidates),
            purged=purged,
            failed=failed,
            skipped=skipped,
        )

    def _is_reclaimable(self, attachment: Attachment, *, now: datetime) -> bool:
        """The domain's answer to "may this row be dropped?", applied by both rules.

        Kept as one predicate so the sweep's defence-in-depth check cannot drift
        from the adapter's candidate query (010).
        """
        if AttachmentRetentionPolicy.is_due(attachment, now=now):
            return True
        return AttachmentRetentionPolicy.is_stale_pending(
            attachment,
            now=now,
            after_seconds=self._limits.presigned_url_ttl_seconds,
        )

    async def _reclaim_expired(self, *, user_id: str) -> None:
        """Best-effort retention on the owner's read path.

        A degraded object store must not break the listing, so the failure is
        counted and logged instead of raised — silently swallowing it is still
        forbidden (050).
        """
        try:
            await self.sweep_expired(user_id=user_id)
        except Exception:
            agent_metrics.record_error("attachments", "retention_sweep_read_path_failed")
            logger.warning("attachment retention sweep failed on the read path")

    async def _purge(self, attachment: Attachment, *, user_id: str) -> None:
        """Drop both objects and the row, then record why it disappeared (020)."""
        await self._delete_chunk_parts(
            attachment.id, up_to_index=AttachmentIntakePolicy.max_chunk_part_index(self._limits)
        )
        await self._blob_store.delete(attachment.blob_key)
        if attachment.derived_text_key:
            await self._blob_store.delete(attachment.derived_text_key)
        await self._repository.delete(attachment.id, user_id=user_id)
        await self._audit(
            event="attachment_expired",
            thread_id=attachment.thread_id or "",
            payload={
                "attachment_id": str(attachment.id),
                "mode": attachment.mode,
                "status": attachment.status,
                "reason": "retention_expired",
            },
        )

    @traceable(name="attachment.delete")
    async def delete(self, *, attachment_id: UUID, user_id: str) -> None:
        """Remove the row and both blobs; a missing row is a typed error (060)."""
        attachment = await self._require(attachment_id, user_id=user_id)
        await self._delete_chunk_parts(
            attachment.id,
            up_to_index=AttachmentIntakePolicy.max_chunk_part_index(self._limits),
        )
        await self._blob_store.delete(attachment.blob_key)
        if attachment.derived_text_key:
            await self._blob_store.delete(attachment.derived_text_key)
        await self._repository.delete(attachment.id, user_id=user_id)
        await self._audit(
            event="attachment_deleted",
            thread_id=attachment.thread_id or "",
            payload={"attachment_id": str(attachment.id)},
        )

    @traceable(name="attachment.build_turn_context")
    async def build_turn_context(
        self,
        *,
        attachment_ids: Sequence[UUID],
        user_id: str,
        thread_id: str | None = None,
    ) -> AttachmentTurnContext:
        """Resolve the fenced blocks that may enter this dialog turn.

        This is the *only* accessor that returns attachment text to the dialog
        path. It fails closed: a quarantined, expired or re-flagged attachment
        aborts the turn instead of silently contributing nothing.
        """
        if not attachment_ids:
            return AttachmentTurnContext()
        if len(attachment_ids) > self._limits.max_attachments_per_turn:
            msg = f"too many attachments for one turn ({len(attachment_ids)})"
            raise ValueError(msg)

        found = await self._repository.get_many(list(attachment_ids), user_id=user_id)
        by_id = {item.id: item for item in found}
        blocks: list[AttachmentContextBlock] = []
        for attachment_id in attachment_ids:
            attachment = by_id.get(attachment_id)
            if attachment is None:
                raise AttachmentNotFoundError(attachment_id)
            blocks.append(await self._fence_for_turn(attachment))
        return AttachmentTurnContext(blocks=tuple(blocks))

    async def compliance_export_for_thread(
        self,
        *,
        thread_id: str,
        owner_user_id: str,
    ) -> tuple[AttachmentComplianceRecord, ...]:
        """Return attachment metadata for a thread (manager/admin API only)."""
        rows = await self.list_for_thread(thread_id=thread_id, user_id=owner_user_id)
        return tuple(
            AttachmentComplianceRecord(
                id=row.id,
                filename=row.filename,
                mime_type=row.mime_type,
                status=row.status,
                rejection_reason=row.rejection_reason,
                created_at=row.created_at,
                expires_at=row.expires_at,
                page_count=row.page_count,
                size_bytes=row.size_bytes,
                contains_pii=row.contains_pii,
            )
            for row in rows
        )

    @traceable(name="attachment.request_quarantine_restore")
    async def request_quarantine_restore(
        self,
        *,
        attachment_id: UUID,
        user_id: str,
        thread_id: str,
        org_id: str | None,
    ) -> HITLCardView:
        """Mint a manager-facing HITL card to release injection quarantine only (020)."""
        if self._hitl is None:
            msg = "attachment quarantine restore requires a configured HITL service"
            raise RuntimeError(msg)
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.status != "quarantined" or attachment.rejection_reason not in _QUARANTINE_RESTORE_REASONS:
            raise AttachmentRestoreNotAllowedError(
                attachment.id,
                status=attachment.status,
                rejection_reason=attachment.rejection_reason,
            )

        task_id = f"{_RESTORE_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = AttachmentRestorePayload(
            task_id=task_id,
            attachment_id=attachment.id,
            user_id=user_id,
            thread_id=thread_id,
            org_id=(org_id or "").strip(),
        )
        await self._store_restore_pending(payload)
        preview = (
            f"restore attachment={attachment.id}; file={attachment.filename}; "
            f"reason={attachment.rejection_reason}; manager override masks injection"
        )
        card = await self._hitl.create_tool_approval_card(
            thread_id=thread_id,
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_RESTORE_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("high"),
            argument_preview=preview,
            owner_user_id=user_id,
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        await self._audit(
            event="attachment_restore_requested",
            thread_id=thread_id,
            payload={"attachment_id": str(attachment.id), "task_id": task_id},
        )
        return card

    @traceable(name="attachment.request_analysis")
    async def request_analysis(
        self,
        *,
        attachment_id: UUID,
        user_id: str,
        thread_id: str,
        org_id: str | None,
        instruction: str,
    ) -> HITLCardView:
        """Mint HITL card for local tabular analysis (G15 ADA; code-exec deferred)."""
        if self._hitl is None:
            msg = "attachment analysis requires a configured HITL service"
            raise RuntimeError(msg)
        if self._analysis is None:
            msg = "attachment analysis sandbox is not configured"
            raise RuntimeError(msg)
        attachment = await self._require(attachment_id, user_id=user_id)
        if not attachment.is_usable:
            raise AttachmentNotUsableError(attachment.id, state=attachment.status)
        mime = attachment.mime_type.strip().lower()
        name = attachment.filename.lower()
        if mime not in _TABULAR_ANALYZE_MIMES and not name.endswith((".csv", ".xlsx", ".txt")):
            raise AttachmentNotUsableError(attachment.id, state="unsupported_for_analysis")

        task_id = f"{_ANALYZE_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = AttachmentAnalyzePayload(
            task_id=task_id,
            attachment_id=attachment.id,
            user_id=user_id,
            thread_id=thread_id,
            org_id=(org_id or "").strip(),
            instruction=instruction.strip()[:4_000],
        )
        await self._store_analyze_pending(payload)
        preview = (
            f"analyze attachment={attachment.id}; file={attachment.filename}; instruction={payload.instruction[:200]}"
        )
        card = await self._hitl.create_tool_approval_card(
            thread_id=thread_id,
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_ANALYZE_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("medium"),
            argument_preview=preview,
            owner_user_id=user_id,
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        await self._audit(
            event="attachment_analysis_requested",
            thread_id=thread_id,
            payload={"attachment_id": str(attachment.id), "task_id": task_id},
        )
        return card

    async def list_connector_sources(
        self,
        *,
        user_id: str,
        org_id: str,
    ) -> tuple[object, ...]:
        """Discover external import sources (G10 — EDMS-first catalog)."""
        if self._connector is None:
            return ()
        return await self._connector.list_sources(user_id=user_id, org_id=org_id)

    async def request_connector_import(
        self,
        *,
        connector_id: str,
        remote_ref: str,
        user_id: str,
        org_id: str,
        thread_id: str,
        project_id: str | None = None,
    ) -> None:
        """Fail-closed EDMS/import seam until MCP write path lands (G10, 092)."""
        from palatium_ai.domain.attachments.errors import AttachmentConnectorUnavailableError
        from palatium_ai.domain.ports.attachment_connector import AttachmentConnectorImportRequest

        if self._connector is None:
            raise AttachmentConnectorUnavailableError(
                connector_id=connector_id,
                reason="attachment connectors are not configured",
            )
        await self._connector.request_import(
            AttachmentConnectorImportRequest(
                connector_id=connector_id,
                remote_ref=remote_ref,
                user_id=user_id,
                org_id=org_id,
                thread_id=thread_id,
                project_id=project_id,
            )
        )

    def last_analysis_result(self, task_id: str) -> dict[str, object] | None:
        """Return the most recent approved analysis payload for UI/tests."""
        raw = self._last_analysis.get(task_id)
        return raw if isinstance(raw, dict) else None

    @traceable(name="attachment.request_index")
    async def request_index(
        self,
        *,
        attachment_id: UUID,
        user_id: str,
        thread_id: str,
        org_id: str | None,
        document_title: str | None = None,
    ) -> HITLCardView:
        """Prepare sanitized chunks and mint the HITL card for knowledge ingest (020)."""
        if self._hitl is None:
            msg = "attachment indexing requires a configured HITL service"
            raise RuntimeError(msg)
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.mode != "index":
            raise AttachmentModeMismatchError(attachment.id, expected="index", actual=attachment.mode)
        if not attachment.is_usable:
            raise AttachmentNotUsableError(attachment.id, state=attachment.status)

        body = await self._reviewed_body(attachment)
        chunks = await self._prepare_index_chunks(
            text=body.text,
            thread_id=thread_id,
            attachment_id=attachment.id,
            mime_type=attachment.mime_type,
            document_title=document_title or attachment.filename,
        )
        if not chunks:
            raise AttachmentNotUsableError(attachment.id, state="empty_content")

        task_id = f"{_INDEX_TASK_PREFIX}{uuid4().hex[:12]}"
        payload = AttachmentIndexPayload(
            task_id=task_id,
            attachment_id=attachment.id,
            user_id=user_id,
            thread_id=thread_id,
            org_id=(org_id or "").strip(),
            document_title=(document_title or attachment.filename)[:256],
            mime_type=attachment.mime_type,
            project_id=attachment.project_id,
            chunks=chunks,
        )
        await self._store_index_pending(payload)
        preview = (
            f"attachment={attachment.id}; file={attachment.filename}; "
            f"chunks={len(chunks)}; pages={attachment.page_count or 0}"
            + (f"; project={attachment.project_id}" if attachment.project_id else "")
        )
        card = await self._hitl.create_tool_approval_card(
            thread_id=thread_id,
            task_id=task_id,
            server_name=_PLATFORM_SERVER,
            tool_name=_INGEST_TOOL,
            side_effect="write",
            risk_score=risk_score_for_tier("high"),
            argument_preview=preview,
            owner_user_id=user_id,
            org_id=org_id,
            ttl_seconds=_PENDING_TTL_SECONDS,
        )
        await self._audit(
            event="attachment_index_requested",
            thread_id=thread_id,
            payload={"attachment_id": str(attachment.id), "chunk_count": str(len(chunks))},
        )
        return card

    @traceable(name="attachment.execute_after_approval")
    async def execute_after_approval(self, *, task_id: str) -> dict[str, object]:
        """Run off-graph attachment mutations after HITL approve (index or restore).

        Named to the shared off-graph tool contract so ``HitlRespondFacade`` can
        resolve any pending mutation without special-casing this service (020).
        """
        if task_id.startswith(_RESTORE_TASK_PREFIX):
            return await self._execute_restore_after_approval(task_id=task_id)
        if task_id.startswith(_ANALYZE_TASK_PREFIX):
            return await self._execute_analyze_after_approval(task_id=task_id)
        payload = await self._load_index_pending(task_id)
        if payload is None:
            msg = f"pending attachment index missing for task_id={task_id}"
            raise ValueError(msg)
        if self._mcp_registry is None:
            msg = "attachment indexing requires a configured MCP registry"
            raise RuntimeError(msg)

        chunks_payload = [
            {"index": chunk.index, "text": chunk.text, "contextual_prefix": chunk.contextual_prefix}
            for chunk in payload.chunks
        ]
        arguments: dict[str, object] = {
            "user_id": payload.user_id,
            "thread_id": payload.thread_id,
            "document_id": payload.knowledge_document_id(),
            "chunks_json": json.dumps(chunks_payload, ensure_ascii=False),
        }
        if payload.document_title:
            arguments["document_title"] = payload.document_title

        outcome = await call_mcp_tool(
            MCPToolCallParams(
                server_name=_PLATFORM_SERVER,
                tool_name=_INGEST_TOOL,
                arguments=arguments,
                actor_user_id=payload.user_id,
                actor_org_id=payload.org_id,
                actor_thread_id=payload.thread_id,
            ),
            self._mcp_registry,
            conversation_id=payload.thread_id,
            repository=self._mcp_tool_call_repository,
        )
        await self._delete_index_pending(task_id)
        if outcome.is_error:
            msg = "ingest_document MCP call failed for attachment index"
            raise RuntimeError(msg)

        await self._mark_indexed(payload)
        await self._audit(
            event="attachment_indexed",
            thread_id=payload.thread_id,
            payload={"attachment_id": str(payload.attachment_id), "chunk_count": str(len(payload.chunks))},
        )
        return {"content": outcome.content, "chunk_count": len(payload.chunks)}

    async def discard_pending(self, *, task_id: str) -> None:
        """Drop a parked index, restore, or analyze payload after a rejected/expired card."""
        if task_id.startswith(_RESTORE_TASK_PREFIX):
            await self._delete_restore_pending(task_id)
            return
        if task_id.startswith(_ANALYZE_TASK_PREFIX):
            await self._delete_analyze_pending(task_id)
            return
        await self._delete_index_pending(task_id)

    async def _execute_restore_after_approval(self, *, task_id: str) -> dict[str, object]:
        payload = await self._load_restore_pending(task_id)
        if payload is None:
            msg = f"pending attachment restore missing for task_id={task_id}"
            raise ValueError(msg)
        attachment = await self._require(payload.attachment_id, user_id=payload.user_id)
        if attachment.status != "quarantined" or attachment.rejection_reason not in _QUARANTINE_RESTORE_REASONS:
            raise AttachmentRestoreNotAllowedError(
                attachment.id,
                status=attachment.status,
                rejection_reason=attachment.rejection_reason,
            )

        saved = await self._apply_manager_restore(attachment)
        await self._delete_restore_pending(task_id)
        await self._audit(
            event="attachment_restore_approved",
            thread_id=payload.thread_id,
            payload={"attachment_id": str(saved.id), "status": saved.status},
        )
        return {"attachment_id": str(saved.id), "status": saved.status}

    async def _apply_manager_restore(self, attachment: Attachment) -> Attachment:
        """Re-admit a quarantined attachment with masked injection (manager path only)."""
        if attachment.derived_text_key:
            content = await self._read_content(attachment)
            report = scan_prompt_injection(content.safe_text)
            prepared = UntrustedContentPolicy.prepare(content.safe_text, report, thresholds=self._thresholds)
            masked_text = (
                prepared.text
                if prepared.action == "mask" and prepared.text
                else redact_findings(
                    content.safe_text,
                    report.findings,
                )
            )
            updated_content = content.model_copy(
                update={
                    "safe_text": masked_text,
                    "scan": content.scan.model_copy(
                        update={
                            "action": "mask",
                            "matched_rules": prepared.matched_rules,
                            "worst_severity": report.worst_severity,
                        },
                    ),
                },
            )
            await self._write_content(attachment.derived_text_key, updated_content)
            return await self._repository.save(
                attachment.model_copy(
                    update={
                        "status": "ready",
                        "rejection_reason": None,
                        "error": None,
                    },
                ),
            )

        outcome = await self._pipeline.run(
            attachment,
            limits=self._limits,
            force_mask_injection=True,
        )
        updated = attachment
        if outcome.content is not None:
            derived_key = AttachmentIntakePolicy.derived_text_key(attachment.id)
            await self._write_content(derived_key, outcome.content)
            updated = attachment.model_copy(update={"derived_text_key": derived_key})
        if not outcome.admitted:
            raise AttachmentNotUsableError(attachment.id, state=outcome.status)
        row_update: dict[str, object] = {
            "status": outcome.status,
            "size_bytes": outcome.stored_size_bytes,
            "rejection_reason": None,
            "error": None,
            "page_count": outcome.content.page_count if outcome.content is not None else None,
            "contains_pii": outcome.content.contains_pii if outcome.content is not None else False,
        }
        if outcome.detected_mime_type:
            row_update["mime_type"] = outcome.detected_mime_type
        return await self._repository.save(updated.model_copy(update=row_update))

    async def _prepare_index_chunks(
        self,
        *,
        text: str,
        thread_id: str,
        attachment_id: UUID,
        mime_type: str,
        document_title: str,
    ) -> tuple[TextChunk, ...]:
        """Chunk (+ contextual prefixes when DocumentIngestService is wired)."""
        if self._document_ingest is not None:
            result = await self._document_ingest.prepare_chunks(
                task_id=f"att-prep-{attachment_id.hex[:12]}",
                thread_id=thread_id,
                raw_text=text,
                document_id=str(attachment_id),
                mime_type=mime_type or None,
                max_chunk_chars=_INDEX_CHUNK_CHARS,
                enrich_context_prefix=True,
                document_title=document_title[:256],
                persist_pending=False,
            )
            if result.output is not None and result.output.chunks:
                return result.output.chunks
            logger.warning(
                "attachment index enrich failed; falling back to plain chunks",
                attachment_id=str(attachment_id),
                status=result.status,
                error=result.error,
            )
        _strategy, chunks = chunk_text(text, max_chars=_INDEX_CHUNK_CHARS)
        return tuple(chunks)

    async def _mark_indexed(self, payload: AttachmentIndexPayload) -> None:
        """Best-effort state transition; the write already happened, so log on drift."""
        try:
            attachment = await self._repository.get(payload.attachment_id, user_id=payload.user_id)
        except Exception:
            logger.warning("attachment index state read failed", attachment_id=str(payload.attachment_id))
            return
        if attachment is None:
            logger.warning("attachment index state drift", attachment_id=str(payload.attachment_id))
            return
        await self._repository.save(attachment.model_copy(update={"status": "indexed"}))

    async def _fence_for_turn(self, attachment: Attachment) -> AttachmentContextBlock:
        """Re-check stored content and wrap it; never returns unfenced text (020)."""
        if attachment.status not in _USABLE_FOR_TURN:
            raise AttachmentNotUsableError(attachment.id, state=attachment.status)
        if attachment.is_expired:
            raise AttachmentNotUsableError(attachment.id, state="expired")
        body = await self._reviewed_body(attachment)
        source = attachment_fence_source(attachment_id=attachment.id, filename=attachment.filename)
        fence_body = body.text
        if body.truncated:
            # Explicit marker so Formatter/Researcher surface incompleteness instead
            # of inventing a mid-word "full text unavailable" paraphrase (065).
            fence_body = f"[attachment extraction truncated — full text unavailable]\n\n{fence_body}"
        return AttachmentContextBlock(
            attachment_id=attachment.id,
            filename=attachment.filename,
            source=source,
            fenced_text=wrap_untrusted_tool_output(fence_body, source=source),
            action=body.action,
            page_count=attachment.page_count or 0,
        )

    async def _reviewed_body(self, attachment: Attachment) -> _ReviewedBody:
        """Load derived content and re-run the injection gate as defence in depth."""
        content = await self._read_content(attachment)
        if not content.is_prompt_eligible:
            raise AttachmentNotUsableError(attachment.id, state=content.scan.action)
        report = scan_prompt_injection(content.safe_text)
        prepared = UntrustedContentPolicy.prepare(content.safe_text, report, thresholds=self._thresholds)
        if not prepared.usable:
            raise AttachmentNotUsableError(attachment.id, state=f"rescan_{prepared.action}")
        return _ReviewedBody(text=prepared.text, action=prepared.action, truncated=content.truncated)

    async def _read_content(self, attachment: Attachment) -> AttachmentContent:
        if not attachment.derived_text_key:
            raise AttachmentContentMissingError(attachment.id)
        try:
            raw = await self._blob_store.read_bytes(attachment.derived_text_key)
        except BlobNotFoundError as exc:
            raise AttachmentContentMissingError(attachment.id) from exc
        return AttachmentContent.model_validate_json(raw)

    async def _write_content(self, key: str, content: AttachmentContent) -> None:
        await self._blob_store.write_bytes(
            key,
            content.model_dump_json().encode("utf-8"),
            content_type=_DERIVED_CONTENT_TYPE,
        )

    async def _require(self, attachment_id: UUID, *, user_id: str) -> Attachment:
        attachment = await self._repository.get(attachment_id, user_id=user_id)
        if attachment is None:
            raise AttachmentNotFoundError(attachment_id)
        return attachment

    async def _create_within_quota(self, attachment: Attachment, *, now: datetime) -> Attachment:
        """Insert the intake row, refusing when the thread's in-flight uploads are exhausted.

        The quota caps *unfinished* uploads per thread, not rows the thread ever
        created. Counting every row (rejected, quarantined and abandoned ones
        included) let five failed attempts lock a thread for the whole attachment
        TTL, so later messages were refused as if they carried too many files. How
        many attachments may *enter one turn* is a separate check in
        :meth:`build_turn_context`.

        The count and the insert happen inside the adapter's transaction under a
        per-thread lock: a read here followed by a write would let two concurrent
        intakes both observe ``limit - 1`` and both pass (020).
        """
        created = await self._repository.create_under_upload_quota(
            attachment,
            limit=self._limits.max_attachments_per_turn,
            pending_cutoff=now - timedelta(seconds=self._limits.presigned_url_ttl_seconds),
        )
        if created is None:
            # The adapter observed the count within its own transaction; re-deriving
            # the threshold here would duplicate the rule, so the typed reason comes
            # from the policy with the limit that was actually applied (010).
            self._raise_intake_refusal(
                AttachmentIntakePolicy.quota_decision(
                    filename=attachment.filename,
                    in_flight=self._limits.max_attachments_per_turn,
                    limits=self._limits,
                )
            )
        return created

    def _raise_intake_refusal(self, decision: IntakeDecision) -> NoReturn:
        """Turn a refused decision into the typed intake error (030: no silent drop)."""
        agent_metrics.record_error("attachments", f"intake_{decision.reason}")
        if decision.reason is None:  # pragma: no cover — refused implies a reason
            raise AttachmentIntakeRejectedError("filename_invalid", filename=decision.filename)
        raise AttachmentIntakeRejectedError(decision.reason, filename=decision.filename)

    async def _store_index_pending(self, payload: AttachmentIndexPayload) -> None:
        self._index_pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(
            f"{_PENDING_PREFIX}{payload.task_id}",
            payload.model_dump_json(),
            ex=_PENDING_TTL_SECONDS,
        )

    async def _load_index_pending(self, task_id: str) -> AttachmentIndexPayload | None:
        if self._redis is None:
            return self._index_pending.get(task_id)
        raw = await self._redis.get(f"{_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._index_pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = AttachmentIndexPayload.model_validate_json(text)
        self._index_pending[task_id] = payload
        return payload

    async def _delete_index_pending(self, task_id: str) -> None:
        self._index_pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_PENDING_PREFIX}{task_id}")

    async def _store_restore_pending(self, payload: AttachmentRestorePayload) -> None:
        self._restore_pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(
            f"{_RESTORE_PENDING_PREFIX}{payload.task_id}",
            payload.model_dump_json(),
            ex=_PENDING_TTL_SECONDS,
        )

    async def _load_restore_pending(self, task_id: str) -> AttachmentRestorePayload | None:
        if self._redis is None:
            return self._restore_pending.get(task_id)
        raw = await self._redis.get(f"{_RESTORE_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._restore_pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = AttachmentRestorePayload.model_validate_json(text)
        self._restore_pending[task_id] = payload
        return payload

    async def _delete_restore_pending(self, task_id: str) -> None:
        self._restore_pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_RESTORE_PENDING_PREFIX}{task_id}")

    async def _execute_analyze_after_approval(self, *, task_id: str) -> dict[str, object]:
        payload = await self._load_analyze_pending(task_id)
        if payload is None:
            msg = f"pending attachment analysis missing for task_id={task_id}"
            raise ValueError(msg)
        if self._analysis is None:
            msg = "attachment analysis sandbox is not configured"
            raise RuntimeError(msg)

        attachment = await self._require(payload.attachment_id, user_id=payload.user_id)
        data = await self._blob_store.read_bytes(attachment.blob_key)
        from palatium_ai.domain.ports.attachment_analysis import AttachmentAnalysisRequest

        result = await self._analysis.analyze(
            AttachmentAnalysisRequest(
                attachment_id=attachment.id,
                user_id=payload.user_id,
                instruction=payload.instruction,
                filename=attachment.filename,
                mime_type=attachment.mime_type,
                data=data,
            ),
        )
        await self._delete_analyze_pending(task_id)
        outcome: dict[str, object] = {
            "attachment_id": str(attachment.id),
            "summary": result.summary,
            "tables_json": result.tables_json,
            "charts_json": result.charts_json,
        }
        self._last_analysis[task_id] = outcome
        await self._audit(
            event="attachment_analysis_completed",
            thread_id=payload.thread_id,
            payload={"attachment_id": str(attachment.id), "task_id": task_id},
        )
        return outcome

    async def _store_analyze_pending(self, payload: AttachmentAnalyzePayload) -> None:
        self._analyze_pending[payload.task_id] = payload
        if self._redis is None:
            return
        await self._redis.set(
            f"{_ANALYZE_PENDING_PREFIX}{payload.task_id}",
            payload.model_dump_json(),
            ex=_PENDING_TTL_SECONDS,
        )

    async def _load_analyze_pending(self, task_id: str) -> AttachmentAnalyzePayload | None:
        if self._redis is None:
            return self._analyze_pending.get(task_id)
        raw = await self._redis.get(f"{_ANALYZE_PENDING_PREFIX}{task_id}")
        if raw is None:
            return self._analyze_pending.get(task_id)
        text = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
        payload = AttachmentAnalyzePayload.model_validate_json(text)
        self._analyze_pending[task_id] = payload
        return payload

    async def _delete_analyze_pending(self, task_id: str) -> None:
        self._analyze_pending.pop(task_id, None)
        if self._redis is not None:
            await self._redis.delete(f"{_ANALYZE_PENDING_PREFIX}{task_id}")

    async def _delete_chunk_parts(self, attachment_id: UUID, *, up_to_index: int) -> None:
        """Best-effort cleanup of staged resumable-upload parts."""
        for index in range(up_to_index):
            await self._blob_store.delete(AttachmentIntakePolicy.chunk_part_key(attachment_id, index))

    @staticmethod
    async def _audit(*, event: str, thread_id: str, payload: dict[str, str]) -> None:
        await get_audit_logger().append_async(
            timestamp=datetime.now(UTC).isoformat(),
            conversation_id=thread_id,
            event=event,
            metadata=payload,
        )


@dataclass(frozen=True, slots=True)
class _ReviewedBody:
    """Sanitized body plus the action that produced it (drives the audit label)."""

    text: str
    action: UntrustedContentAction
    truncated: bool = False


__all__ = [
    "AttachmentComplianceRecord",
    "AttachmentDownloadTicket",
    "AttachmentService",
    "AttachmentSweepResult",
    "AttachmentUploadTicket",
]
