# src/palatium_ai/application/agents/formatter/worker_writer.py

"""Deterministic render for worker-owned turns (P1b, single-writer contract).

When the worker already wrote the deliverable, the Formatter has nothing to
compile: parsing the worker GFM into a ``ContentDocument`` is the whole job. No
LLM call means no second writer and no replaced answer — the document contains
exactly the text the client already saw as a draft.

Fail-open is deliberate: an empty/truncated draft, a composition request, or a
locale mismatch falls back to the existing Formatter LLM path. Losing structure is
recoverable; showing a broken answer is not (055).
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Literal

from palatium_ai.application.agents.formatter.config import (
    MIN_PIPELINE_CONFIDENCE,
    FormatterStyleHint,
)
from palatium_ai.application.agents.formatter.markdown_parser import markdown_to_content_document
from palatium_ai.application.agents.formatter.parsing import align_formatter_meta, resolve_style_hint
from palatium_ai.core.logging import get_logger
from palatium_ai.domain.agents.formatter import FormatterInput
from palatium_ai.domain.content import ContentDocument
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

logger = get_logger(__name__)

#: Composition hints the deterministic renderer can honour: the draft's own shape
#: is the deliverable (no brand sections, no cards, no restructure).
PRESERVING_STYLE_HINTS: frozenset[str] = frozenset(
    {"plain_text", "content_generation", "document_generation"},
)

#: Worker summaries are clipped with a trailing ellipsis; a tail marker means the
#: draft is provably incomplete and must be rewritten, not shown (055).
_TRUNCATION_MARKERS = (
    "[attachment extraction truncated]",
    "[attachment body truncated]",
)
_TRAILING_ELLIPSIS = re.compile(r"[…]\s*$")

RenderReason = Literal[
    "rendered",
    "empty_source",
    "low_confidence",
    "composition_required",
    "truncated",
    "locale_mismatch",
    "no_blocks",
]


@dataclass(frozen=True)
class WorkerRenderDecision:
    """Result of the deterministic worker render: a document or a fallback reason."""

    document: ContentDocument | None
    reason: RenderReason

    @property
    def rendered(self) -> bool:
        return self.document is not None


def render_worker_document(
    task_input: FormatterInput,
    *,
    worker_confidence: float | None,
) -> WorkerRenderDecision:
    """Render the worker draft without an LLM, or name why the LLM path must own it."""
    source = (task_input.worker_summary or "").strip()
    if not source:
        return WorkerRenderDecision(document=None, reason="empty_source")
    if worker_confidence is None or worker_confidence < MIN_PIPELINE_CONFIDENCE:
        return WorkerRenderDecision(document=None, reason="low_confidence")
    style_hint: FormatterStyleHint = resolve_style_hint(task_input)
    if style_hint not in PRESERVING_STYLE_HINTS:
        return WorkerRenderDecision(document=None, reason="composition_required")
    if _is_truncated(source):
        return WorkerRenderDecision(document=None, reason="truncated")

    document = markdown_to_content_document(source, task_input)
    if not document.blocks:
        return WorkerRenderDecision(document=None, reason="no_blocks")
    if not ReplyLocalePolicy.prose_matches_locale(source, task_input.response_locale):
        return WorkerRenderDecision(document=None, reason="locale_mismatch")
    confidence = min(max(float(worker_confidence), 0.0), 1.0)
    document = document.model_copy(
        update={"meta": document.meta.model_copy(update={"confidence": confidence})},
    )
    return WorkerRenderDecision(document=align_formatter_meta(document, task_input), reason="rendered")


def _is_truncated(source: str) -> bool:
    lowered = source.lower()
    return bool(_TRAILING_ELLIPSIS.search(source)) or any(marker in lowered for marker in _TRUNCATION_MARKERS)
