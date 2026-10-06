# src/palatium_ai/presentation/api/routers/attachments.py

"""Attachment intake, scan status and HITL-gated knowledge indexing (020)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field

from palatium_ai.domain.attachments.errors import (
    AttachmentError,
    AttachmentModeMismatchError,
    AttachmentNotFoundError,
    AttachmentNotUsableError,
    AttachmentUploadTooLargeError,
)
from palatium_ai.domain.hitl.cards import HITLCardView
from palatium_ai.domain.sessions.errors import SessionOwnershipError
from palatium_ai.presentation.resources import get_app_resources
from palatium_ai.presentation.security.deps import get_principal
from palatium_ai.presentation.security.ownership import load_session_for_principal

if TYPE_CHECKING:
    # Type-only: presentation may not import application at runtime (000).
    from palatium_ai.application.services.attachment_service import AttachmentService
    from palatium_ai.domain.attachments.models import Attachment

router = APIRouter()

AttachmentStatus = Literal[
    "pending",
    "uploaded",
    "scanning",
    "ready",
    "quarantined",
    "rejected",
    "expired",
    "indexed",
]


class InitUploadRequest(BaseModel):
    """Client-declared metadata for an upload that will be PUT straight to storage."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    filename: str = Field(min_length=1, max_length=255)
    mime_type: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(gt=0)
    #: ``attach`` = usable for this dialog turn; ``index`` = knowledge candidate
    #: that still needs an approved HITL card before anything is written (020).
    mode: Literal["attach", "index"] = "attach"


class InitUploadResponse(BaseModel):
    """Presigned PUT target plus the attachment identity the client must reuse."""

    model_config = {"frozen": True}

    attachment_id: UUID
    upload_url: str
    expires_at: datetime
    mode: Literal["attach", "index"]


class AttachmentResponse(BaseModel):
    """Attachment state as the client sees it; never exposes blob keys (020)."""

    model_config = {"frozen": True}

    attachment_id: UUID
    thread_id: str | None = None
    filename: str
    mime_type: str
    size_bytes: int
    mode: Literal["attach", "index"]
    status: AttachmentStatus
    page_count: int | None = None
    rejection_reason: str | None = None
    error: str | None = None
    created_at: datetime
    expires_at: datetime | None = None


class AttachmentListResponse(BaseModel):
    model_config = {"frozen": True}

    thread_id: str
    items: tuple[AttachmentResponse, ...] = ()


class AttachmentSweepResponse(BaseModel):
    """Counters from one retention pass over the caller's own attachments (060)."""

    model_config = {"frozen": True}

    considered: int = Field(ge=0)
    purged: int = Field(ge=0)
    failed: int = Field(ge=0)
    skipped: int = Field(ge=0)


class IndexRequest(BaseModel):
    """Request the HITL card for durable knowledge ingestion."""

    model_config = {"frozen": True}

    thread_id: str = Field(min_length=1, max_length=128)
    document_title: str | None = Field(default=None, max_length=256)


def _to_response(attachment: Attachment) -> AttachmentResponse:
    """Map a domain ``Attachment`` onto the client-facing view."""
    return AttachmentResponse(
        attachment_id=attachment.id,
        thread_id=attachment.thread_id,
        filename=attachment.filename,
        mime_type=attachment.mime_type,
        size_bytes=attachment.size_bytes,
        mode=attachment.mode,
        status=attachment.status,
        page_count=attachment.page_count,
        rejection_reason=attachment.rejection_reason,
        error=attachment.error,
        created_at=attachment.created_at,
        expires_at=attachment.expires_at,
    )


def _attachment_service(request: Request) -> AttachmentService:
    """Resolve the service or answer 503 — never ``None`` leaking into handlers."""
    resources = get_app_resources(request.app)
    service = resources.attachment_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Attachments are disabled",
        )
    return service


def _error_status(exc: AttachmentError) -> int:
    """Map typed attachment errors onto HTTP status codes."""
    if isinstance(exc, AttachmentNotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(exc, (AttachmentModeMismatchError, AttachmentNotUsableError)):
        return status.HTTP_409_CONFLICT
    return status.HTTP_400_BAD_REQUEST


async def _read_body_capped(request: Request, *, max_bytes: int) -> bytes:
    """Read the request body, refusing to buffer more than ``max_bytes`` (020, 080).

    ``Content-Length`` is checked first as a cheap early exit, but it is a client
    claim, so the cap is enforced again while streaming: a lying or absent header
    must not make the API hold an unbounded payload in memory.
    """
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"upload exceeds the {max_bytes} byte cap",
        )

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"upload exceeds the {max_bytes} byte cap",
            )
    return bytes(body)


@router.post("/init", response_model=InitUploadResponse, status_code=status.HTTP_201_CREATED)
async def init_upload(body: InitUploadRequest, request: Request) -> InitUploadResponse:
    """Validate intake and issue a presigned PUT URL for the raw bytes."""
    principal = get_principal(request)
    service = _attachment_service(request)

    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=get_app_resources(request.app).session_service,
        thread_id=body.thread_id,
        allow_missing=False,
    )

    try:
        ticket = await service.init_upload(
            user_id=principal.subject,
            filename=body.filename,
            mime_type=body.mime_type,
            size_bytes=body.size_bytes,
            mode=body.mode,
            thread_id=body.thread_id,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc

    return InitUploadResponse(
        attachment_id=ticket.attachment_id,
        upload_url=ticket.upload_url,
        expires_at=ticket.expires_at,
        mode=body.mode,
    )


@router.post("/{attachment_id}/complete", response_model=AttachmentResponse)
async def complete_upload(attachment_id: UUID, request: Request) -> AttachmentResponse:
    """Run the scan/parse/injection pipeline once the blob is actually present."""
    principal = get_principal(request)
    service = _attachment_service(request)

    try:
        attachment = await service.complete_upload(
            attachment_id=attachment_id,
            user_id=principal.subject,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc
    return _to_response(attachment)


@router.put("/{attachment_id}/content", response_model=AttachmentResponse)
async def upload_attachment_content(attachment_id: UUID, request: Request) -> AttachmentResponse:
    """Accept the raw bytes through the API instead of the presigned URL (020).

    ``POST /init`` remains the primary path: it hands back a presigned PUT and the
    bytes never touch this process. This route covers the two cases where that is
    not possible — a backend whose URL has no HTTP surface of its own (the
    in-process dev store) and a deployment that keeps object storage off the
    client's network. It reuses the same row, the same cap and the same pipeline:
    the object is written as ``uploaded`` and stays unusable until
    ``POST /{id}/complete`` re-reads the size from storage and scans it.

    The body is stored with the MIME type the row was accepted with, because that
    pair was already validated by intake policy; a body that disagrees with it is
    caught by the parser and refused (fail closed).
    """
    principal = get_principal(request)
    service = _attachment_service(request)

    data = await _read_body_capped(request, max_bytes=service.max_upload_bytes)
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="upload body is empty",
        )

    try:
        attachment = await service.receive_upload(
            attachment_id=attachment_id,
            user_id=principal.subject,
            data=data,
        )
    except AttachmentUploadTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=str(exc),
        ) from exc
    except AttachmentError as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc
    return _to_response(attachment)


@router.get("", response_model=AttachmentListResponse)
async def list_attachments(thread_id: str, request: Request) -> AttachmentListResponse:
    """List the caller's attachments for one owned thread."""
    principal = get_principal(request)
    service = _attachment_service(request)

    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=get_app_resources(request.app).session_service,
        thread_id=thread_id,
        allow_missing=False,
    )

    try:
        items = await service.list_for_thread(thread_id=thread_id, user_id=principal.subject)
    except AttachmentError as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc
    return AttachmentListResponse(
        thread_id=thread_id,
        items=tuple(_to_response(item) for item in items),
    )


@router.post("/sweep", response_model=AttachmentSweepResponse)
async def sweep_attachments(request: Request) -> AttachmentSweepResponse:
    """Reclaim the caller's expired attachments and their stored objects (020, 060).

    Exposed per owner rather than as a global maintenance call: ``attachments`` is
    under ``FORCE ROW LEVEL SECURITY``, so the app role cannot see other tenants'
    rows, and this endpoint must therefore never be read as a full-system purge.
    """
    principal = get_principal(request)
    service = _attachment_service(request)

    result = await service.sweep_expired(user_id=principal.subject)
    return AttachmentSweepResponse(
        considered=result.considered,
        purged=result.purged,
        failed=result.failed,
        skipped=result.skipped,
    )


@router.get("/{attachment_id}", response_model=AttachmentResponse)
async def get_attachment(attachment_id: UUID, request: Request) -> AttachmentResponse:
    """Return one attachment owned by the caller."""
    principal = get_principal(request)
    service = _attachment_service(request)

    try:
        attachment = await service.get(
            attachment_id=attachment_id,
            user_id=principal.subject,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc
    return _to_response(attachment)


@router.post("/{attachment_id}/index", response_model=HITLCardView)
async def request_index(
    attachment_id: UUID,
    body: IndexRequest,
    request: Request,
) -> HITLCardView:
    """Mint the HITL card for ``platform.ingest_document`` (020, 070).

    Nothing is written to the knowledge base here: the card is returned, and the
    write only happens when the user approves it through ``/api/hitl``.
    """
    principal = get_principal(request)
    service = _attachment_service(request)

    await load_session_for_principal(
        request=request,
        principal=principal,
        session_service=get_app_resources(request.app).session_service,
        thread_id=body.thread_id,
        allow_missing=False,
    )

    try:
        card = await service.request_index(
            attachment_id=attachment_id,
            user_id=principal.subject,
            thread_id=body.thread_id,
            org_id=principal.org_id,
            document_title=body.document_title,
        )
    except AttachmentError as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return card.without_secrets()


@router.delete("/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(attachment_id: UUID, request: Request) -> None:
    """Delete the row and both blobs for an owned attachment."""
    principal = get_principal(request)
    service = _attachment_service(request)

    try:
        await service.delete(attachment_id=attachment_id, user_id=principal.subject)
    except AttachmentError as exc:
        raise HTTPException(status_code=_error_status(exc), detail=str(exc)) from exc


__all__ = [
    "AttachmentListResponse",
    "AttachmentResponse",
    "AttachmentSweepResponse",
    "IndexRequest",
    "InitUploadRequest",
    "InitUploadResponse",
    "SessionOwnershipError",
    "router",
]
