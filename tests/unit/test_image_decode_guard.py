# tests/unit/test_image_decode_guard.py

"""G13: raster pixel / dimension guard before OCR."""

from __future__ import annotations

import pytest

from palatium_ai.domain.ports.document_parser import DocumentParseError
from palatium_ai.infrastructure.parsing.image_decode_guard import assert_image_decode_within_budget


def _tiny_png() -> bytes:
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (8, 8), color="white").save(buffer, format="PNG")
    return buffer.getvalue()


def test_assert_image_decode_accepts_small_png() -> None:
    assert_image_decode_within_budget(_tiny_png())


def test_assert_image_decode_refuses_oversized_dimensions() -> None:
    from io import BytesIO

    from PIL import Image

    from palatium_ai.domain.attachments.image_limits import MAX_IMAGE_DIMENSION_PX

    buffer = BytesIO()
    side = MAX_IMAGE_DIMENSION_PX + 1
    # Header-only geometry is enough; pixels are not materialised in the file.
    Image.new("RGB", (side, 8), color="black").save(buffer, format="PNG")
    with pytest.raises(DocumentParseError) as excinfo:
        assert_image_decode_within_budget(buffer.getvalue())
    assert excinfo.value.rejection_reason == "image_too_large"
