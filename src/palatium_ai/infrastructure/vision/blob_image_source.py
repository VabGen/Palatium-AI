# src/palatium_ai/infrastructure/vision/blob_image_source.py

"""Blob-backed byte source for chat image parts (ADR 0007, 020).

Storage is the authority, not the caller: a message can claim ``image/png`` while the
object is a 40 MiB PDF-named-as-PNG. Every suspicious fact therefore comes from
``BlobStorePort.stat`` and from the bytes themselves:

* key is derived from the attachment id (content-addressed, no filename, no traversal);
* missing object → refuse (a part whose bytes vanished must not reach the model);
* media type reported by the store must match the part and be inside the closed
  vision whitelist — a mismatch is tampering, not a conversion opportunity;
* byte cap is applied twice: against ``stat`` (cheap) and against the read payload
  (a lying stat must not buy an unbounded upload);
* pixel/dimension guard before the adapter base64-encodes anything, so a decompression
  bomb is refused here instead of inside the provider call.
"""

from __future__ import annotations

from uuid import UUID

import structlog

from palatium_ai.domain.attachments.policies import AttachmentIntakePolicy
from palatium_ai.domain.llm.errors import VisionImageUnavailableError
from palatium_ai.domain.llm.models import VISION_IMAGE_MIMES
from palatium_ai.domain.policies.vision import normalise_image_mime
from palatium_ai.domain.ports.blob_store import BlobStorePort
from palatium_ai.domain.ports.document_parser import DocumentParseError
from palatium_ai.infrastructure.parsing.image_decode_guard import assert_image_decode_within_budget

logger = structlog.get_logger(__name__)


class BlobVisionImageSource:
    """``VisionImageSourcePort`` implementation over the attachment blob store."""

    def __init__(self, blob_store: BlobStorePort, *, max_image_bytes: int) -> None:
        self._blob_store = blob_store
        self._max_image_bytes = max_image_bytes

    async def read(self, attachment_id: UUID, *, expected_mime: str) -> bytes:
        """Read the stored image, refusing anything the store does not corroborate."""
        key = AttachmentIntakePolicy.blob_key(attachment_id)
        stat = await self._blob_store.stat(key)
        if stat is None:
            logger.warning("vision.image_missing", attachment_id=str(attachment_id))
            raise VisionImageUnavailableError("image blob is missing")

        expected = normalise_image_mime(expected_mime)
        stored = normalise_image_mime(stat.content_type or "")
        if stored and stored != expected:
            logger.warning(
                "vision.image_mime_mismatch",
                attachment_id=str(attachment_id),
                expected=expected,
                stored=stored,
            )
            raise VisionImageUnavailableError("stored media type does not match the part")
        if expected not in VISION_IMAGE_MIMES:
            raise VisionImageUnavailableError("media type is outside the vision whitelist")
        if stat.size_bytes <= 0:
            raise VisionImageUnavailableError("image blob is empty")
        if stat.size_bytes > self._max_image_bytes:
            logger.warning(
                "vision.image_too_large",
                attachment_id=str(attachment_id),
                size_bytes=stat.size_bytes,
                max_bytes=self._max_image_bytes,
            )
            raise VisionImageUnavailableError("image exceeds the vision byte cap")

        data = await self._blob_store.read_bytes(key)
        if not data:
            raise VisionImageUnavailableError("image blob is empty")
        if len(data) > self._max_image_bytes:
            raise VisionImageUnavailableError("image payload exceeds the vision byte cap")
        try:
            assert_image_decode_within_budget(data)
        except DocumentParseError as exc:
            # Guard text is safe to surface: it names a limit, never the payload.
            raise VisionImageUnavailableError(str(exc)) from exc
        return data


__all__ = ["BlobVisionImageSource"]
