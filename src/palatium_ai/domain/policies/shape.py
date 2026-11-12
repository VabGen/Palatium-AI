# src/palatium_ai/domain/policies/shape.py

"""Form of the answer body (``response_shape``) as a domain policy (055).

``task_kind`` says *what* the user wants; ``response_shape`` says *how* the answer is
assembled from ``ContentDocument`` blocks. The two are orthogonal: a comparison can be
a table or prose, a knowledge request can be a plan.

The document contract itself is not extended here — every shape is a composition of
existing block types (``domain/content/content_document.py``); ADR 0005 records why
per-scenario schemas were rejected. This module owns the only check of that
composition, so renderers and prompts never grow their own copies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, Field

from palatium_ai.domain.content.content_document import ContentDocument
from palatium_ai.domain.policies.types import (
    RESPONSE_SHAPE_DEFAULT,
    ResponseShape,
    TaskKind,
)

_VALID: Final[frozenset[str]] = frozenset({"auto", "comparison_table", "document_analysis", "inventory", "plan", "prose"})
#: Outcomes that have no substantive body — a shape would only create a false mismatch.
_BODYLESS_KINDS: Final[frozenset[str]] = frozenset({"social_conversation", "clarification_needed"})

# Verification floor for comparison: an attribute column plus two compared objects.
_MIN_COMPARISON_COLUMNS = 3
_MIN_COMPARISON_ROWS = 2
_MIN_PLAN_ITEMS = 2
_MIN_ANALYSIS_HEADINGS = 2
_MIN_INVENTORY_ITEMS = 2


@dataclass(frozen=True, slots=True)
class ShapeRecipe:
    """What a shape expects from the document; consumed by :meth:`validate`."""

    shape: ResponseShape
    #: Block types of which at least one must be present (stable ``ContentBlock.type``).
    block_requirements: tuple[str, ...]
    min_table_columns: int = 0
    min_table_rows: int = 0


_RECIPES: Final[dict[str, ShapeRecipe]] = {
    "comparison_table": ShapeRecipe(
        shape="comparison_table",
        block_requirements=("table",),
        min_table_columns=_MIN_COMPARISON_COLUMNS,
        min_table_rows=_MIN_COMPARISON_ROWS,
    ),
    "document_analysis": ShapeRecipe(
        # Dense Kimi-style analysis: ≥2 headings + structured body checked in
        # ``_check_document_analysis`` (kv and/or list+callout).
        shape="document_analysis",
        block_requirements=("heading",),
    ),
    "inventory": ShapeRecipe(
        # Unordered catalogue («перечисли N… только список») — ListBlock, not Steps.
        shape="inventory",
        block_requirements=("list",),
    ),
    "plan": ShapeRecipe(
        # Process answers must use StepsBlock so BlockRenderer draws one timeline —
        # an ordered list is parallel/sequence prose and drifts into mixed numbering.
        shape="plan",
        block_requirements=("steps",),
    ),
    "prose": ShapeRecipe(
        shape="prose",
        block_requirements=("paragraph",),
    ),
}

_MISSING_REASON: Final[dict[str, str]] = {
    "table": "table_block_missing",
    "heading": "heading_block_missing",
    "steps": "plan_block_missing",
    "list": "list_block_missing",
    "paragraph": "paragraph_block_missing",
}


class ShapeVerdict(BaseModel):
    """Deterministic outcome of one shape check (stable reasons for metrics/logs)."""

    model_config = {"frozen": True}

    shape: ResponseShape
    satisfied: bool
    reason: str = Field(min_length=1, max_length=64)


class ShapeRecipePolicy:
    """Pure policy: coerce the axis, resolve its recipe, verify the finished document."""

    @classmethod
    def coerce(cls, raw: object) -> ResponseShape:
        """Unknown / absent labels fall back to ``auto`` — never constrain by guess."""
        if isinstance(raw, str) and raw.strip() in _VALID:
            return raw.strip()  # type: ignore[return-value]  # membership in the closed Literal set (017)
        return RESPONSE_SHAPE_DEFAULT

    @classmethod
    def resolve(cls, *, shape: object, task_kind: TaskKind | str | None) -> ShapeRecipe | None:
        """Return the recipe, or ``None`` when the shape is not applicable to this turn."""
        kind = cls.coerce(shape)
        if kind == "auto":
            return None
        if isinstance(task_kind, str) and task_kind in _BODYLESS_KINDS:
            return None
        return _RECIPES.get(kind)

    @classmethod
    def validate(cls, document: ContentDocument, recipe: ShapeRecipe) -> ShapeVerdict:
        """Check block composition; never raises and never mutates the document."""
        # Plan has its own reason codes (steps vs ordered-list drift) — do not collapse
        # an ordered list into the generic ``plan_block_missing`` before that check.
        if recipe.shape == "plan":
            return _verdict(recipe.shape, _check_plan(document))
        if not _has_required_block(document, recipe):
            return _verdict(recipe.shape, _missing_reason(recipe))
        reason = _specific_check(document, recipe)
        return _verdict(recipe.shape, reason)


def _has_required_block(document: ContentDocument, recipe: ShapeRecipe) -> bool:
    present = {block.type for block in document.blocks}
    return any(required in present for required in recipe.block_requirements)


def _missing_reason(recipe: ShapeRecipe) -> str:
    primary = recipe.block_requirements[0] if recipe.block_requirements else ""
    return _MISSING_REASON.get(primary, "required_block_missing")


def _specific_check(document: ContentDocument, recipe: ShapeRecipe) -> str:
    match recipe.shape:
        case "comparison_table":
            return _check_comparison_table(document, recipe)
        case "plan":
            return _check_plan(document)
        case "document_analysis":
            return _check_document_analysis(document)
        case "inventory":
            return _check_inventory(document)
        case _:
            return "ok"


def _check_inventory(document: ContentDocument) -> str:
    """Require ≥2 unordered list items (catalogue, not a numbered process)."""
    items = 0
    for block in document.blocks:
        if block.type == "list" and block.style != "ordered":
            items = max(items, len(block.items))
    if items >= _MIN_INVENTORY_ITEMS:
        return "ok"
    if items:
        return "inventory_too_short"
    return "list_block_missing"


def _check_document_analysis(document: ContentDocument) -> str:
    """Require scannable hierarchy: ≥2 headings and structured body (kv or list+callout)."""
    headings = sum(1 for block in document.blocks if block.type == "heading")
    if headings < _MIN_ANALYSIS_HEADINGS:
        return "analysis_too_few_headings"
    has_kv = any(block.type == "kv" for block in document.blocks)
    has_list = any(block.type == "list" for block in document.blocks)
    has_callout = any(block.type == "callout" for block in document.blocks)
    if has_kv or (has_list and has_callout):
        return "ok"
    if has_list:
        return "analysis_structure_thin"
    return "analysis_structure_missing"


def _check_comparison_table(document: ContentDocument, recipe: ShapeRecipe) -> str:
    narrow = False
    for block in document.blocks:
        if block.type != "table" or len(block.columns) < recipe.min_table_columns:
            continue
        narrow = True
        if len(block.rows) >= recipe.min_table_rows:
            return "ok"
    return "table_too_short" if narrow else "table_too_narrow"


def _check_plan(document: ContentDocument) -> str:
    items = 0
    ordered_list_only = False
    for block in document.blocks:
        if block.type == "steps":
            items = max(items, len(block.items))
        elif block.type == "list" and block.style == "ordered":
            ordered_list_only = True
    if items >= _MIN_PLAN_ITEMS:
        return "ok"
    if items:
        return "plan_too_short"
    # Ordered list is no longer an accepted plan surface — metric reason stays stable.
    return "plan_not_ordered" if ordered_list_only else "plan_block_missing"


def _verdict(shape: ResponseShape, reason: str) -> ShapeVerdict:
    return ShapeVerdict(shape=shape, satisfied=reason == "ok", reason=reason)


__all__ = [
    "ShapeRecipe",
    "ShapeRecipePolicy",
    "ShapeVerdict",
]
