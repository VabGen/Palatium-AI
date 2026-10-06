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
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from palatium_ai.application.agents.text_ingestor.chunking import chunk_text
from palatium_ai.application.services.attachment_pipeline import AttachmentPipeline
from palatium_ai.application.tools.mcp import MCPToolCallParams, call_mcp_tool
from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.core.security.prompt_injection import scan_prompt_injection
from palatium_ai.domain.attachments import (
    DEFAULT_ATTACHMENT_LIMITS,
    Attachment,
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
    AttachmentRetentionPolicy,
    AttachmentTurnContext,
    AttachmentUploadTooLargeError,
)
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

    from palatium_ai.application.services.hitl_service import HitlService
    from palatium_ai.domain.hitl.cards import HITLCardView
    from palatium_ai.domain.ports.attachments import AttachmentRepositoryPort
    from palatium_ai.domain.ports.blob_store import BlobStorePort
    from palatium_ai.domain.ports.mcp import MCPRegistryPort, McpToolCallRecorderPort

logger = get_logger(__name__)

_DERIVED_CONTENT_TYPE = "application/json"
_PENDING_PREFIX = "attachment_index:pending:"
_PENDING_TTL_SECONDS = 5 * 60
_INDEX_TASK_PREFIX = "att-index-"
_PLATFORM_SERVER = "platform"
_INGEST_TOOL = "ingest_document"
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
        self._limits = limits
        self._thresholds = thresholds
        self._index_pending: dict[str, AttachmentIndexPayload] = {}

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
    ) -> AttachmentUploadTicket:
        """Validate intake, create the PENDING row and issue a presigned PUT URL."""
        existing = await self._count_existing(thread_id=thread_id, user_id=user_id)
        decision = AttachmentIntakePolicy.validate(
            filename=filename,
            mime_type=mime_type,
            size_bytes=size_bytes,
            existing_count=existing,
            limits=self._limits,
        )
        if decision.refused:
            agent_metrics.record_error("attachments", f"intake_{decision.reason}")
            if decision.reason is None:  # pragma: no cover — refused implies a reason
                raise AttachmentIntakeRejectedError("filename_invalid", filename=decision.filename)
            raise AttachmentIntakeRejectedError(decision.reason, filename=decision.filename)

        now = datetime.now(UTC)
        attachment_id = uuid4()
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
            created_at=now,
            expires_at=AttachmentIntakePolicy.expiry_for(mode, now=now, limits=self._limits),
        )
        created = await self._repository.create(attachment)
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

    @traceable(name="attachment.complete_upload")
    async def complete_upload(self, *, attachment_id: UUID, user_id: str) -> Attachment:
        """Confirm the upload and run the scan/parse/injection pipeline exactly once."""
        attachment = await self._require(attachment_id, user_id=user_id)
        if attachment.status not in ("pending", "uploaded"):
            return attachment

        outcome = await self._pipeline.run(attachment, limits=self._limits)
        updated = attachment
        if outcome.content is not None:
            derived_key = AttachmentIntakePolicy.derived_text_key(attachment.id)
            await self._write_content(derived_key, outcome.content)
            updated = attachment.model_copy(update={"derived_text_key": derived_key})
        updated = updated.model_copy(
            update={
                "status": outcome.status,
                "size_bytes": outcome.stored_size_bytes,
                "rejection_reason": outcome.rejection_reason,
                "error": outcome.error,
                "page_count": outcome.content.page_count if outcome.content is not None else None,
            },
        )
        saved = await self._repository.save(updated)
        await self._audit(
            event="attachment_completed",
            thread_id=saved.thread_id or "",
            payload={
                "attachment_id": str(saved.id),
                "status": saved.status,
                "rejection_reason": saved.rejection_reason or "",
                "page_count": str(saved.page_count or 0),
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
        batch = self._limits.retention_sweep_batch if limit is None else limit
        candidates = await self._repository.list_expired(reference, user_id=user_id, limit=batch)
        purged = 0
        failed = 0
        skipped = 0
        for attachment in candidates:
            if not AttachmentRetentionPolicy.is_due(attachment, now=reference):
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
        _strategy, chunks = chunk_text(body.text, max_chars=_INDEX_CHUNK_CHARS)
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
            chunks=chunks,
        )
        await self._store_index_pending(payload)
        preview = (
            f"attachment={attachment.id}; file={attachment.filename}; "
            f"chunks={len(chunks)}; pages={attachment.page_count or 0}"
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
        """Run ``platform.ingest_document`` after HITL approve and mark the row indexed.

        Named to the shared off-graph tool contract so ``HitlRespondFacade`` can
        resolve any pending mutation without special-casing this service (020).
        """
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
            "document_id": str(payload.attachment_id),
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
        """Drop a parked index payload after a rejected/expired card."""
        await self._delete_index_pending(task_id)

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
        source = f"attachment:{attachment.filename}"
        return AttachmentContextBlock(
            attachment_id=attachment.id,
            filename=attachment.filename,
            source=source[:128],
            fenced_text=wrap_untrusted_tool_output(body.text, source=source),
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
        return _ReviewedBody(text=prepared.text, action=prepared.action)

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

    async def _count_existing(self, *, thread_id: str | None, user_id: str) -> int:
        if not thread_id:
            return 0
        return await self._repository.count_for_thread(thread_id, user_id=user_id)

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


__all__ = ["AttachmentService", "AttachmentSweepResult", "AttachmentUploadTicket"]
