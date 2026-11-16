# src/palatium_ai/domain/content/revision.py

"""Content identity and block diff for revised answers (W7b, 050).

``ContentDocument`` has no block ids, and adding model-generated ids would be the
classic self-marking failure: the model invents “b3” and the client highlights the wrong
paragraph. Identity is therefore *derived* — a hash of the block's canonical JSON, so the
same content always has the same id and the same content on both sides of a diff.

Two hashes, two jobs:

* ``block_content_hash`` — identity of one block, stable across position, block order,
  reformatting of the surrounding document, and repeated turns;
* ``document_content_hash`` — identity of the whole answer (locale/title/blocks). Meta
  fields that legitimately change every turn (``confidence``, provider ``citations``,
  server-owned ``verbosity_budget``) are excluded: a re-render of the same text is not a
  revision.
"""

from __future__ import annotations

import hashlib
import json

from collections import Counter

from pydantic import BaseModel

from palatium_ai.domain.content.content_document import ContentBlock, ContentDocument

#: 64-bit block ids: a thread would need ~4·10⁹ distinct blocks for a birthday collision,
#: while a 12-block diff stays readable in the persisted turn payload.
_BLOCK_HASH_CHARS = 16
#: 128-bit document identity: a revision reference must survive far longer than a diff.
_DOCUMENT_HASH_CHARS = 32


class DocumentRevision(BaseModel):
    """Server-computed delta between the previous answer and this one.

    ``changed_blocks`` are hashes present in the new document and absent (in that
    multiplicity) in the previous one — added *or* rewritten blocks; a block that merely
    moved is unchanged, because identity is content, not position.

    ``changed_block_indices`` are where those blocks sit in the *current* document, in the
    same order. The client paints from indices on purpose: re-deriving a Python hash in
    TypeScript would be a second implementation of an identity contract, and a silent
    mismatch (float formatting, a new field) would just make the highlight disappear.
    Hashes stay the identity for history; indices are the paint map.
    """

    model_config = {"frozen": True}

    revision_of: str
    changed_blocks: tuple[str, ...] = ()
    changed_block_indices: tuple[int, ...] = ()
    removed_blocks: tuple[str, ...] = ()
    unchanged_blocks: int = 0


def _canonical(payload: object) -> str:
    """Stable JSON: key order and whitespace must not change a hash."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def block_content_hash(block: ContentBlock) -> str:
    """Stable id of one block's content (same text → same id, any position)."""
    digest = hashlib.sha256(_canonical(block.model_dump(mode="json")).encode())
    return digest.hexdigest()[:_BLOCK_HASH_CHARS]


def document_content_hash(document: ContentDocument) -> str:
    """Identity of the answer's content — excludes meta that changes per generation."""
    digest = hashlib.sha256(
        _canonical(
            {
                "locale": document.locale,
                "title": document.title,
                "blocks": [block.model_dump(mode="json") for block in document.blocks],
            }
        ).encode()
    )
    return digest.hexdigest()[:_DOCUMENT_HASH_CHARS]


def document_revision(previous: ContentDocument, current: ContentDocument) -> DocumentRevision:
    """Block-level delta from ``previous`` to ``current`` (multiset, order-preserving).

    Duplicate blocks are counted, not collapsed: deleting one of two identical
    paragraphs is a real removal, and adding a second copy is a real change.
    """
    before = Counter(block_content_hash(block) for block in previous.blocks)
    after = Counter(block_content_hash(block) for block in current.blocks)

    remaining = Counter(before)
    changed: list[str] = []
    changed_indices: list[int] = []
    for index, block in enumerate(current.blocks):
        digest = block_content_hash(block)
        if remaining[digest] > 0:
            remaining[digest] -= 1
        else:
            changed.append(digest)
            changed_indices.append(index)

    return DocumentRevision(
        revision_of=document_content_hash(previous),
        changed_blocks=tuple(changed),
        changed_block_indices=tuple(changed_indices),
        removed_blocks=tuple(sorted((before - after).elements())),
        unchanged_blocks=len(current.blocks) - len(changed),
    )
