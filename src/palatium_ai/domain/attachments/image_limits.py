# src/palatium_ai/domain/attachments/image_limits.py

"""Closed decode budgets for raster attachments (010, 080)."""

from __future__ import annotations

# Decompression bombs: refuse before full decode / OCR (G13).
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_DIMENSION_PX = 16_384

__all__ = ["MAX_IMAGE_DIMENSION_PX", "MAX_IMAGE_PIXELS"]
