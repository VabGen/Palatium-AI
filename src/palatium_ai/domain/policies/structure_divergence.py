"""Structure divergence between a worker draft and the final document.

Pre-P1 gate for single-writer turns (``writer=worker``): the worker owns the
*structure* and the Formatter must not re-construct it. Two independent signals,
both deterministic (no embeddings, no LLM):

* ``shingle_containment`` — what share of the final document's 3-token windows
  also occur in the worker draft. Low containment = the final answer re-phrases
  (or contradicts) what the worker wrote, i.e. a second generation.
* ``block_coverage`` — what share of the final document's blocks carry text the
  worker draft already contained. Low coverage = the Formatter *added* structure
  the worker never produced (hallucinated sections, invented tables).

``structure_divergence = 1 - shingle_containment``. The two are reported
separately because they fail differently: paraphrase pulls containment down
while coverage stays high; added blocks pull coverage down first.
"""

from __future__ import annotations

import re

from dataclasses import dataclass

from palatium_ai.domain.content.content_document import (
    CalloutBlock,
    CodeBlock,
    ContentBlock,
    ContentDocument,
    HeadingBlock,
    KeyValueBlock,
    ListBlock,
    ParagraphBlock,
    StepsBlock,
    TableBlock,
)

SHINGLE_SIZE = 3
#: A block counts as covered when at least this share of its shingles is present.
BLOCK_COVERAGE_THRESHOLD = 0.8

_MARKUP = re.compile(r"[*_`>#|\[\]()~]+")
_NON_WORD = re.compile(r"[^\w]+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class StructureDivergence:
    """Deterministic rewrite/expansion signals for one turn."""

    shingle_containment: float
    block_coverage: float
    structure_divergence: float
    final_shingles: int
    final_blocks: int
    uncovered_blocks: int


def _normalize(text: str) -> str:
    """Lowercase, strip markdown markup, collapse whitespace and punctuation."""
    return _NON_WORD.sub(" ", _MARKUP.sub(" ", text.lower())).strip()


def _shingles(tokens: list[str]) -> set[tuple[str, ...]]:
    if len(tokens) < SHINGLE_SIZE:
        return {tuple(tokens)} if tokens else set()
    return {tuple(tokens[i : i + SHINGLE_SIZE]) for i in range(len(tokens) - SHINGLE_SIZE + 1)}


def _block_text(block: ContentBlock) -> str:
    match block:
        case ParagraphBlock() | HeadingBlock():
            return block.text
        case CalloutBlock():
            return " ".join(part for part in (block.title, block.body) if part)
        case CodeBlock():
            return block.content
        case ListBlock():
            return " ".join(item.text for item in block.items)
        case KeyValueBlock():
            return " ".join(f"{item.label} {item.value}" for item in block.items)
        case StepsBlock():
            return " ".join(f"{item.title} {item.body}" for item in block.items)
        case TableBlock():
            cells = [*block.columns, *(cell for row in block.rows for cell in row)]
            return " ".join(cells)
        case _:
            # Formula/chart/widget/divider carry no prose to compare against.
            return ""


def _contains(haystack: list[str], needle: list[str]) -> bool:
    """True when ``needle`` occurs contiguously in ``haystack`` (short blocks)."""
    if not needle:
        return False
    width = len(needle)
    return any(haystack[i : i + width] == needle for i in range(len(haystack) - width + 1))


def measure_structure_divergence(worker_text: str, document: ContentDocument) -> StructureDivergence:
    """Compare the worker draft with the final document it was rendered into."""
    worker_tokens = _normalize(worker_text).split()
    worker_shingles = _shingles(worker_tokens)
    block_texts = [text for block in document.blocks if (text := _block_text(block))]
    final_tokens: list[str] = []
    covered = 0
    for text in block_texts:
        tokens = _normalize(text).split()
        final_tokens.extend(tokens)
        if not tokens:
            covered += 1
            continue
        if len(tokens) < SHINGLE_SIZE:
            # A short heading has fewer tokens than one shingle: match it verbatim.
            if _contains(worker_tokens, tokens):
                covered += 1
            continue
        block_shingles = _shingles(tokens)
        hit = len(block_shingles & worker_shingles) / len(block_shingles)
        if hit >= BLOCK_COVERAGE_THRESHOLD:
            covered += 1

    final_shingles = _shingles(final_tokens)
    containment = len(final_shingles & worker_shingles) / len(final_shingles) if final_shingles else 1.0
    blocks = len(block_texts)
    coverage = covered / blocks if blocks else 1.0
    return StructureDivergence(
        shingle_containment=round(containment, 4),
        block_coverage=round(coverage, 4),
        structure_divergence=round(1.0 - containment, 4),
        final_shingles=len(final_shingles),
        final_blocks=blocks,
        uncovered_blocks=blocks - covered,
    )
