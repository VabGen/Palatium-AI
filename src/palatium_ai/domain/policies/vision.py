# src/palatium_ai/domain/policies/vision.py

"""Admission policy for image messages (ADR 0007, 020/060).

Vision is a *cost and privacy* boundary, not a formatting choice: one forwarded image
can carry PII the OCR path would have masked, and vision tokens are priced differently
from text. The decision therefore lives in one deterministic policy instead of an
``if`` at each call site, so the attachment pipeline, the agent layer and the adapter
cannot disagree about whether an image may travel.

Fail-closed by construction:

* mime outside ``VISION_IMAGE_MIMES`` — the provider would answer 400 after we paid;
* empty blob or a size above the configured cap — storage is not an authority the
  caller can override;
* ``contains_pii`` — images with PII are **not** sent unless the owner turned on
  ``ALLOW_PII_IMAGES`` for the deployment (020/060). The flag is off by default and
  every forwarded PII image is an auditable decision (:attr:`VisionDecision.pii_forwarded`
  → span event ``gen_ai.pii_image_allowed`` + metric), never a silent pass;
* no ``vision_model`` alias configured — the gateway has nothing to route to.

Reason precedence is structural → PII → configuration: a malformed image is reported
as such even when it is also PII, and PII is never reported as "not configured".

Two reasons are decided by the caller, not by :meth:`VisionPolicy.decide`, because they
are facts about the blob and the call rather than about the image:

* ``image_missing`` — the store has no object for the id (nothing to forward);
* ``too_many_images`` — this image is beyond the per-call cap (``LLM_VISION_MAX_IMAGES``).

Both still travel as the same ``VisionBlockReason``, so an operator sees one vocabulary.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from palatium_ai.domain.llm.models import VISION_IMAGE_MIMES

VisionBlockReason = Literal[
    "unsupported_mime",
    "image_missing",
    "image_empty",
    "image_too_large",
    "pii_blocked",
    "vision_not_configured",
    "too_many_images",
]


def normalise_image_mime(mime_type: str) -> str:
    """Lowercase + strip parameters (``image/png; charset=binary`` → ``image/png``).

    One normalisation for the policy, the blob-backed source and the adapter: two
    spellings of the same media type must not produce two different decisions.
    """
    return (mime_type or "").split(";", 1)[0].strip().casefold()


class VisionDecision(BaseModel):
    """Whether one image may be forwarded, and the single reason when it may not."""

    model_config = {"frozen": True}

    allowed: bool
    reason: VisionBlockReason | None = None
    #: True when the image is PII-flagged *and* travelled anyway because the owner
    #: enabled ``ALLOW_PII_IMAGES``. The caller must emit the audit signal (020, 040);
    #: carrying it on the decision is what makes "we forwarded PII" impossible to forget.
    pii_forwarded: bool = False

    @classmethod
    def allow(cls, *, pii_forwarded: bool = False) -> VisionDecision:
        return cls(allowed=True, pii_forwarded=pii_forwarded)

    @classmethod
    def deny(cls, reason: VisionBlockReason) -> VisionDecision:
        return cls(allowed=False, reason=reason)


class VisionPolicy:
    """Pure domain policy: can this image be attached to a model call?"""

    @staticmethod
    def decide(
        *,
        mime_type: str,
        size_bytes: int,
        contains_pii: bool,
        vision_model: str | None,
        max_image_bytes: int,
        allow_pii_images: bool = False,
    ) -> VisionDecision:
        if normalise_image_mime(mime_type) not in VISION_IMAGE_MIMES:
            return VisionDecision.deny("unsupported_mime")
        if size_bytes <= 0:
            return VisionDecision.deny("image_empty")
        if size_bytes > max_image_bytes:
            return VisionDecision.deny("image_too_large")
        if contains_pii and not allow_pii_images:
            return VisionDecision.deny("pii_blocked")
        if not (vision_model or "").strip():
            return VisionDecision.deny("vision_not_configured")
        return VisionDecision.allow(pii_forwarded=contains_pii)
