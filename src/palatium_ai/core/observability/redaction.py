# src/palatium_ai/core/observability/redaction.py

"""PII/token redaction for observability boundaries.

Contract:
  - Pure function, idempotent, no I/O.
  - Applied at every observability boundary: logger, metrics helpers, OTel.
  - Never applied to user-facing responses (user's own data).
  - PII patterns come from ``domain/pii`` (one registry); this module only adds the
    log-only classes (tokens, JWT, filesystem paths) and the truncation policy.
"""

from __future__ import annotations

import hashlib
import re

from typing import Final

from palatium_ai.core.security.pii import scrub_pii

DEFAULT_MAX_LEN: Final = 256

#: Log-only classes. Tokens/paths are not PII, and secrets stay in the scanner (020).
_PATTERNS: Final[list[tuple[re.Pattern[str], str]]] = [
    (
        re.compile(r"\b(sk|pk|ghp|gho|AKIA|xox[baprs])[-_][A-Za-z0-9_-]{16,}\b"),
        "<token>",
    ),
    (
        re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
        "<jwt>",
    ),
    (re.compile(r"(?:/Users/|/home/|C:\\Users\\)[^\s]+"), "<path>"),
]


def redact(text: str | None, *, max_len: int = DEFAULT_MAX_LEN) -> str | None:
    """Truncate then mask PII/token-shaped substrings. Idempotent on already-masked text."""
    if not text:
        return text
    out = scrub_pii(text[:max_len], profile="observability", style="angle")
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out


def hash8(text: str | None) -> str:
    """Stable, non-reversible short hash for grouping without PII."""
    if not text:
        return ""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def bucket_len(text: str | None) -> str:
    """Cardinality-safe length bucket."""
    if not text:
        return "empty"
    n = len(text)
    if n < 50:
        return "0-50"
    if n < 200:
        return "50-200"
    if n < 1000:
        return "200-1k"
    return "1k+"


def set_query_span_attributes(span: object, query: str | None, *, capture_raw: bool = False) -> None:
    """Attach query.hash / query.len_bucket; raw query only when capture_raw (dev)."""
    set_attribute = getattr(span, "set_attribute", None)
    if not callable(set_attribute):
        return
    set_attribute("query.hash", hash8(query))
    set_attribute("query.len_bucket", bucket_len(query))
    if capture_raw and query:
        set_attribute("query", redact(query) or "")
