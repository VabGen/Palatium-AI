# src/palatium_ai/infrastructure/parsing/image_decode_guard.py

"""Pillow-backed pixel/dimension guard before image OCR (G13, 020)."""

from __future__ import annotations

from io import BytesIO

from palatium_ai.domain.attachments.image_limits import MAX_IMAGE_DIMENSION_PX, MAX_IMAGE_PIXELS
from palatium_ai.domain.ports.document_parser import DocumentParseError


def assert_image_decode_within_budget(data: bytes) -> None:
    """Refuse images whose declared geometry exceeds the configured decode budget."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - install-dependent
        msg = "Pillow is required to decode images; install attachments extras"
        raise DocumentParseError(msg) from exc

    previous_cap = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                _raise_image_too_large("image has invalid dimensions")
            if width > MAX_IMAGE_DIMENSION_PX or height > MAX_IMAGE_DIMENSION_PX:
                _raise_image_too_large("image dimension exceeds the configured cap")
            if width * height > MAX_IMAGE_PIXELS:
                _raise_image_too_large("image pixel count exceeds the configured cap")
            image.load()
    except DocumentParseError:
        raise
    except Image.DecompressionBombError as exc:
        _raise_image_too_large("image exceeds Pillow decompression budget", cause=exc)
    except OSError as exc:
        raise DocumentParseError("image is corrupt or not a supported raster") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_cap


def _raise_image_too_large(message: str, *, cause: BaseException | None = None) -> None:
    raise DocumentParseError(message, rejection_reason="image_too_large") from cause


__all__ = ["assert_image_decode_within_budget"]
