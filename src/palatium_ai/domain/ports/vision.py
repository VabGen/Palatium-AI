# src/palatium_ai/domain/ports/vision.py

"""Port that turns an ``ImagePart`` reference into the bytes a model can receive.

The domain message carries a reference, not a payload (ADR 0007): the blob store is
the single owner of upload bytes, and inlining base64 into ``ChatMessage`` would make
every log line, trace attribute and cache key a potential copy of the image (020).

``read`` is deliberately storage-truth-first — an adapter must decide on the size and
media type reported by the store, never on what the caller wrote into the message.
Every failure is a typed :class:`~palatium_ai.domain.llm.errors.VisionImageUnavailableError`,
so the LLM layer fails closed instead of sending a text-only call that would make the
model claim the image is blank.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID


class VisionImageSourcePort(Protocol):
    """Byte source for one image part; implementations must never return foreign bytes."""

    async def read(self, attachment_id: UUID, *, expected_mime: str) -> bytes:
        """Return the stored bytes for an approved part.

        Raises:
            VisionImageUnavailableError: blob missing, media type mismatch against
                storage, or the payload exceeds the vision byte cap.
        """
        ...


__all__ = ["VisionImageSourcePort"]
