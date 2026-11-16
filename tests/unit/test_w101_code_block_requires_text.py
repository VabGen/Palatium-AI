"""W10.1 P0.1a — CodeBlock.content must be non-empty (schema fail-closed)."""

from __future__ import annotations

import pytest

from pydantic import ValidationError

from palatium_ai.domain.content import CodeBlock


def test_w101_code_block_requires_text() -> None:
    with pytest.raises(ValidationError):
        CodeBlock(type="code", language="python", content="")
    with pytest.raises(ValidationError):
        CodeBlock(type="code", language="python", content="   ")
    ok = CodeBlock(type="code", language="python", content="def f():\n    return 1\n")
    assert "def f" in ok.content
