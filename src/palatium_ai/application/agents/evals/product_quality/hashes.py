# src/palatium_ai/application/agents/evals/product_quality/hashes.py

"""Hash pins for W9 judge prompts (ADR-0012)."""

from __future__ import annotations

import hashlib
import re

from pathlib import Path

_PROMPTS = Path(__file__).resolve().parent / "w9_judge_prompts.py"
_ADR_0012 = Path(__file__).resolve().parents[6] / "docs" / "adr" / "0012-product-quality-evals.md"

_HASH_LINE = re.compile(r"^w9_judge_prompts_sha256:\s*(?P<h>[0-9a-f]{64})\s*$", re.MULTILINE)


def w9_judge_prompts_sha256() -> str:
    return hashlib.sha256(_PROMPTS.read_bytes()).hexdigest()


def read_adr_0012_judge_hash() -> str:
    text = _ADR_0012.read_text(encoding="utf-8")
    match = _HASH_LINE.search(text)
    if not match:
        msg = "ADR-0012 missing w9_judge_prompts_sha256 pin"
        raise ValueError(msg)
    return match.group("h")


__all__ = ["read_adr_0012_judge_hash", "w9_judge_prompts_sha256"]
