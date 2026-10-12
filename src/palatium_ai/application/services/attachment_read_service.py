# src/palatium_ai/application/services/attachment_read_service.py

"""On-demand attachment body reads with lazy OCR / Vision write-through (070)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import logger
from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import traceable
from palatium_ai.domain.attachments.content import AttachmentContent
from palatium_ai.domain.attachments.errors import (
    AttachmentNotFoundError,
    AttachmentNotUsableError,
    AttachmentTooLargeError,
)
from palatium_ai.domain.attachments.policies import (
    DEFAULT_ATTACHMENT_LIMITS,
    AttachmentIntakePolicy,
    AttachmentLimits,
)
from palatium_ai.domain.attachments.read import (
    AttachmentReadRequest,
    AttachmentReadResult,
    extraction_source_to_extract_status,
    extraction_source_to_ocr_engine,
)
from palatium_ai.domain.ports.blob_store import BlobNotFoundError

if TYPE_CHECKING:
    from palatium_ai.application.services.attachment_pipeline import AttachmentPipeline
    from palatium_ai.domain.attachments import Attachment
    from palatium_ai.domain.ports.attachments import AttachmentRepositoryPort
    from palatium_ai.domain.ports.blob_store import BlobStorePort

_USABLE = frozenset({"ready", "indexed"})
_DERIVED_CONTENT_TYPE = "application/json"
_EMPTY_NOTICE = (
    "Текст не извлечён: Tesseract и LLM Vision недоступны или не дали результата. "
    "Файл остаётся в хранилище; повторите позже или загрузите текстовую версию."
)


class AttachmentReadService:
    """Owner-scoped read with derived-blob cache and DocumentParserPort cascade."""

    def __init__(
        self,
        *,
        repository: AttachmentRepositoryPort,
        blob_store: BlobStorePort,
        pipeline: AttachmentPipeline,
        limits: AttachmentLimits = DEFAULT_ATTACHMENT_LIMITS,
    ) -> None:
        self._repository = repository
        self._blob_store = blob_store
        self._pipeline = pipeline
        self._limits = limits

    @traceable(name="attachment_read.read")
    async def read(self, request: AttachmentReadRequest) -> AttachmentReadResult:
        """Return sliced text; soft ``notice`` when OCR/Vision both fail (035)."""
        attachment = await self._repository.get(request.attachment_id, user_id=request.user_id)
        if attachment is None:
            raise AttachmentNotFoundError(request.attachment_id)
        if attachment.status not in _USABLE:
            raise AttachmentNotUsableError(attachment.id, state=attachment.status)
        if attachment.size_bytes > self._limits.max_size_bytes:
            raise AttachmentTooLargeError(
                attachment.id,
                size_bytes=attachment.size_bytes,
                max_size_bytes=self._limits.max_size_bytes,
            )

        if not request.force_ocr:
            cached = await self._try_cached(attachment, request)
            if cached is not None:
                agent_metrics.record_attachment_read(
                    kind="cached",
                    ocr_applied=False,
                    ocr_engine=cached.ocr_engine or "none",
                    ocr_cached=True,
                )
                logger.info(
                    "attachment_read.ocr_cached",
                    attachment_id=str(attachment.id),
                    chars=cached.total_chars,
                )
                return cached

        return await self._lazy_parse(attachment, request)

    async def _try_cached(
        self,
        attachment: Attachment,
        request: AttachmentReadRequest,
    ) -> AttachmentReadResult | None:
        content = await self._load_content(attachment)
        if content is None or not content.safe_text.strip():
            return None
        return self._slice_result(
            attachment,
            text=content.safe_text,
            truncated_source=content.truncated,
            request=request,
            ocr_applied=False,
            ocr_cached=True,
            ocr_engine=content.metadata.ocr_engine,
            extract_status=extraction_source_to_extract_status(
                content.metadata.extraction_source,
                text_chars=len(content.safe_text),
            ),
        )

    async def _lazy_parse(
        self,
        attachment: Attachment,
        request: AttachmentReadRequest,
    ) -> AttachmentReadResult:
        try:
            data = await self._blob_store.read_bytes(attachment.blob_key)
        except BlobNotFoundError:
            logger.warning("attachment_read.blob_missing", attachment_id=str(attachment.id))
            return self._empty_notice(attachment, request)

        content = await self._pipeline.reparse_bytes(
            attachment,
            data,
            mime_type=attachment.mime_type,
        )
        if content is None or not content.safe_text.strip():
            engine = content.metadata.ocr_engine if content is not None else None
            agent_metrics.record_attachment_read(
                kind="lazy_empty",
                ocr_applied=True,
                ocr_engine=engine or "none",
                ocr_cached=False,
            )
            logger.info(
                "attachment_read.ocr_applied",
                attachment_id=str(attachment.id),
                ocr_engine=engine,
                chars=0,
                empty=True,
            )
            if content is not None:
                await self._persist(attachment, content, ocr_applied=True)
            return self._empty_notice(attachment, request, ocr_engine=engine)

        await self._persist(attachment, content, ocr_applied=True)
        engine = content.metadata.ocr_engine or extraction_source_to_ocr_engine(
            content.metadata.extraction_source,
        )
        agent_metrics.record_attachment_read(
            kind="lazy",
            ocr_applied=True,
            ocr_engine=engine or "none",
            ocr_cached=False,
        )
        logger.info(
            "attachment_read.ocr_applied",
            attachment_id=str(attachment.id),
            ocr_engine=engine,
            chars=len(content.safe_text),
        )
        return self._slice_result(
            attachment,
            text=content.safe_text,
            truncated_source=content.truncated,
            request=request,
            ocr_applied=True,
            ocr_cached=False,
            ocr_engine=engine,
            extract_status=extraction_source_to_extract_status(
                content.metadata.extraction_source,
                text_chars=len(content.safe_text),
            ),
        )

    async def _persist(
        self,
        attachment: Attachment,
        content: AttachmentContent,
        *,
        ocr_applied: bool,
    ) -> None:
        derived_key = attachment.derived_text_key or AttachmentIntakePolicy.derived_text_key(attachment.id)
        await self._blob_store.write_bytes(
            derived_key,
            content.model_dump_json().encode("utf-8"),
            content_type=_DERIVED_CONTENT_TYPE,
        )
        chars = len(content.safe_text)
        status = extraction_source_to_extract_status(
            content.metadata.extraction_source,
            text_chars=chars,
        )
        await self._repository.update_extraction_state(
            attachment.id,
            user_id=attachment.user_id,
            ocr_applied=ocr_applied,
            extract_status=status,
            extracted_chars=chars,
            derived_text_key=derived_key,
            page_count=content.page_count,
            contains_pii=content.contains_pii,
        )

    async def _load_content(self, attachment: Attachment) -> AttachmentContent | None:
        if not attachment.derived_text_key:
            return None
        try:
            raw = await self._blob_store.read_bytes(attachment.derived_text_key)
        except BlobNotFoundError:
            return None
        return AttachmentContent.model_validate_json(raw)

    def _empty_notice(
        self,
        attachment: Attachment,
        request: AttachmentReadRequest,
        *,
        ocr_engine: str | None = None,
    ) -> AttachmentReadResult:
        return AttachmentReadResult(
            attachment_id=attachment.id,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            text="",
            truncated=False,
            offset=request.offset,
            total_chars=0,
            ocr_applied=True,
            ocr_cached=False,
            ocr_engine=ocr_engine if ocr_engine in ("tesseract", "llm_vision") else None,
            extract_status="empty",
            notice=_EMPTY_NOTICE,
        )

    @staticmethod
    def _slice_result(
        attachment: Attachment,
        *,
        text: str,
        truncated_source: bool,
        request: AttachmentReadRequest,
        ocr_applied: bool,
        ocr_cached: bool,
        ocr_engine: str | None,
        extract_status: str | None,
    ) -> AttachmentReadResult:
        total = len(text)
        start = min(request.offset, total)
        end = min(start + request.max_chars, total)
        sliced = text[start:end]
        truncated = truncated_source or end < total or start > 0
        engine = ocr_engine if ocr_engine in ("tesseract", "llm_vision") else None
        status = extract_status if extract_status in ("text_ok", "ocr_ok", "vision_ok", "empty") else None
        return AttachmentReadResult(
            attachment_id=attachment.id,
            filename=attachment.filename,
            mime_type=attachment.mime_type,
            text=sliced,
            truncated=truncated,
            offset=start,
            total_chars=total,
            ocr_applied=ocr_applied,
            ocr_cached=ocr_cached,
            ocr_engine=engine,
            extract_status=status,
            notice=None,
        )


__all__ = ["AttachmentReadService"]
