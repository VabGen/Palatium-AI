# src/palatium_ai/application/services/vision_images.py

"""Turn images for a chat call: attachment rows → approved ``ImagePart``s (ADR 0007).

This is the only place that decides *which* uploaded images may be looked at by a
model. Keeping it in one application service (instead of an ``if`` at each call site)
means the answer path, the attachment path and the adapter cannot disagree about PII,
media type or size.

Two callers, one decision:

* :meth:`VisionImageService.images_for` — rows resolved by an owner-scoped query;
* :meth:`VisionImageService.parts_for_blocks` — the turn's already-fenced blocks, so the
  graph can admit images once at entry instead of per worker node.

Both build the same :class:`_ImageCandidate` and run the same selection loop, so the two
entry points cannot drift into different policies (050).

Owner scope is required and explicit:

* the caller passes rows it already resolved for one owner — the service never queries
  by id alone, so RLS and the ``user_id`` predicate stay in the repository (060);
* PII classification comes from the row (written by the pipeline that scanned the
  content), and a PII image is *denied* unless the owner enabled ``ALLOW_PII_IMAGES``;
  an allowed PII image carries ``pii_forwarded`` and is audited on every call;
* media type and size are re-read from the blob store, because a client-provided mime
  can lie and the row may predate a re-detection (020);
* every denial carries a typed reason and is counted, so "the model ignored my picture"
  is diagnosable instead of invisible (040).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import cast
from uuid import UUID

import structlog

from pydantic import BaseModel

from palatium_ai.core.observability.metrics import agent_metrics
from palatium_ai.core.observability.tracing import add_span_event
from palatium_ai.domain.attachments.context import AttachmentContextBlock
from palatium_ai.domain.attachments.models import Attachment
from palatium_ai.domain.attachments.policies import AttachmentIntakePolicy
from palatium_ai.domain.llm.models import ImageMime, ImagePart
from palatium_ai.domain.policies.vision import (
    VisionBlockReason,
    VisionDecision,
    VisionPolicy,
    normalise_image_mime,
)
from palatium_ai.domain.ports.blob_store import BlobStorePort

logger = structlog.get_logger(__name__)

#: Span event emitted for every PII image the owner chose to forward (020, 040).
PII_IMAGE_ALLOWED_EVENT = "gen_ai.pii_image_allowed"
#: Metric reason for an allowed PII image — distinct from ``none`` on purpose, so a
#: dashboard can count the exception without parsing the span (040).
PII_ALLOWED_REASON = "pii_allowed"


class VisionImageDenial(BaseModel):
    """One image that may not travel, with the single reason why."""

    model_config = {"frozen": True}

    attachment_id: UUID
    filename: str
    reason: VisionBlockReason


class VisionImagesOutcome(BaseModel):
    """Approved parts plus the denials that explain every omission."""

    model_config = {"frozen": True}

    parts: tuple[ImagePart, ...] = ()
    denials: tuple[VisionImageDenial, ...] = ()

    @property
    def has_images(self) -> bool:
        return bool(self.parts)


@dataclass(frozen=True, slots=True)
class _ImageCandidate:
    """One attachment as the policy needs to see it, independent of its source."""

    attachment_id: UUID
    filename: str
    #: ``None`` means the store has no object for the id (nothing to forward).
    mime_type: str | None
    size_bytes: int
    contains_pii: bool


class VisionImageService:
    """Builds owner-scoped image parts for one turn; fail-closed on every doubt."""

    def __init__(
        self,
        blob_store: BlobStorePort,
        *,
        vision_model: str | None,
        max_image_bytes: int,
        max_images: int,
        allow_pii_images: bool = False,
    ) -> None:
        self._blob_store = blob_store
        self._vision_model = vision_model
        self._max_image_bytes = max_image_bytes
        self._max_images = max(1, max_images)
        # Owner decision, default off: when on, a PII image travels but is audited
        # (span event + metric + warning) instead of vanishing without a trace (020).
        self._allow_pii_images = allow_pii_images

    async def images_for(
        self,
        attachments: Sequence[Attachment],
        *,
        user_id: str,
    ) -> VisionImagesOutcome:
        """Return the parts allowed for this owner; a refused image is a denial, not a raise."""
        candidates: list[_ImageCandidate] = []
        for attachment in attachments:
            if attachment.user_id != user_id:
                # A foreign row reaching a model is a caller bug, not a policy outcome:
                # answering it with a denial would hide the broken owner filter (060).
                msg = "attachment does not belong to the requesting user"
                raise ValueError(msg)
            mime, size_bytes = await self._storage_facts(attachment)
            candidates.append(
                _ImageCandidate(
                    attachment_id=attachment.id,
                    filename=attachment.filename,
                    mime_type=mime,
                    size_bytes=size_bytes,
                    contains_pii=attachment.contains_pii,
                )
            )
        return self._select(candidates)

    async def parts_for_blocks(self, blocks: Sequence[AttachmentContextBlock]) -> VisionImagesOutcome:
        """Admit the turn's already-resolved blocks; non-image blocks are not candidates.

        The block was built from an owner-scoped row, so its id is safe to stat; media
        type and size still come from the store, because the vision gate must not trust
        a value the caller could have re-typed (ADR 0007).
        """
        candidates: list[_ImageCandidate] = []
        for block in blocks:
            if not block.is_image:
                continue
            candidates.append(await self._block_candidate(block))
        return self._select(candidates)

    async def _block_candidate(self, block: AttachmentContextBlock) -> _ImageCandidate:
        stat = await self._blob_store.stat(AttachmentIntakePolicy.blob_key(block.attachment_id))
        if stat is None:
            return _ImageCandidate(
                attachment_id=block.attachment_id,
                filename=block.filename,
                mime_type=None,
                size_bytes=0,
                contains_pii=block.contains_pii,
            )
        stored = normalise_image_mime(stat.content_type or "")
        return _ImageCandidate(
            attachment_id=block.attachment_id,
            filename=block.filename,
            mime_type=stored or normalise_image_mime(block.mime_type),
            size_bytes=stat.size_bytes,
            contains_pii=block.contains_pii,
        )

    async def _storage_facts(self, attachment: Attachment) -> tuple[str | None, int]:
        """Media type and size from the store; the row is only the fallback.

        A missing object yields ``None`` rather than the row's mime: the part would be
        produced and then fail at read time, i.e. after the call was assembled.
        """
        stat = await self._blob_store.stat(AttachmentIntakePolicy.blob_key(attachment.id))
        if stat is None:
            return None, attachment.size_bytes
        stored = normalise_image_mime(stat.content_type or "")
        if stored:
            return stored, stat.size_bytes
        # Some backends report no content type; the row's intake-validated value wins
        # over "unknown", and the size still comes from the store (020).
        return normalise_image_mime(attachment.mime_type), stat.size_bytes

    def _select(self, candidates: Sequence[_ImageCandidate]) -> VisionImagesOutcome:
        """Single selection loop for both entry points: one precedence, one vocabulary."""
        parts: list[ImagePart] = []
        denials: list[VisionImageDenial] = []
        for candidate in candidates:
            mime = candidate.mime_type
            if mime is None:
                denials.append(self._deny(candidate, "image_missing"))
                continue
            if not mime.startswith("image/"):
                continue
            if len(parts) >= self._max_images:
                denials.append(self._deny(candidate, "too_many_images"))
                continue
            decision = VisionPolicy.decide(
                mime_type=mime,
                size_bytes=candidate.size_bytes,
                contains_pii=candidate.contains_pii,
                vision_model=self._vision_model,
                max_image_bytes=self._max_image_bytes,
                allow_pii_images=self._allow_pii_images,
            )
            if not decision.allowed:
                denials.append(self._deny(candidate, decision.reason or "unsupported_mime"))
                continue
            self._record(candidate, decision)
            parts.append(ImagePart(attachment_id=candidate.attachment_id, mime=cast("ImageMime", mime)))

        logger.info(
            "vision.turn_images",
            attachment_count=len(candidates),
            allowed=len(parts),
            denied=len(denials),
            reasons=sorted({denial.reason for denial in denials}),
        )
        return VisionImagesOutcome(parts=tuple(parts), denials=tuple(denials))

    def _record(self, candidate: _ImageCandidate, decision: VisionDecision) -> None:
        reason = PII_ALLOWED_REASON if decision.pii_forwarded else (decision.reason or "none")
        if decision.pii_forwarded:
            # The owner opted in (ALLOW_PII_IMAGES); the exception must still be
            # greppable in traces and countable in Prometheus, not just in a log line.
            add_span_event(
                PII_IMAGE_ALLOWED_EVENT,
                {
                    "attachment_id": str(candidate.attachment_id),
                    "gen_ai.request.model": self._vision_model or "",
                },
            )
            logger.warning(
                "vision.pii_image_forwarded",
                attachment_id=str(candidate.attachment_id),
                reason="allow_pii_images",
            )
        agent_metrics.record_vision_image(outcome="allowed", reason=reason)
        logger.info(
            "vision.image_decision",
            attachment_id=str(candidate.attachment_id),
            outcome="allowed",
            reason=reason,
        )

    @staticmethod
    def _deny(candidate: _ImageCandidate, reason: VisionBlockReason) -> VisionImageDenial:
        agent_metrics.record_vision_image(outcome="denied", reason=reason)
        logger.info(
            "vision.image_decision",
            attachment_id=str(candidate.attachment_id),
            outcome="denied",
            reason=reason,
        )
        return VisionImageDenial(
            attachment_id=candidate.attachment_id,
            filename=candidate.filename,
            reason=reason,
        )


__all__ = [
    "PII_ALLOWED_REASON",
    "PII_IMAGE_ALLOWED_EVENT",
    "VisionImageDenial",
    "VisionImageService",
    "VisionImagesOutcome",
]
