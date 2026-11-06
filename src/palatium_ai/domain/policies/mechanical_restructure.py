# src/palatium_ai/domain/policies/mechanical_restructure.py

"""0-LLM reshape of a persisted ``ContentDocument`` (response-shapes wave 3).

When the user asks to restructure / apply an explicit ``response_shape`` and the prior
answer already holds typed blocks, inventing new facts via Formatter LLM is wasteful
and risks layout thrash. This policy only rearranges existing blocks — never invents
cell values, step titles or section prose (055). If the target shape cannot be met
from the prior blocks alone, return ``None`` and let Formatter call the LLM.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from palatium_ai.domain.content.content_document import (
    CalloutBlock,
    CodeBlock,
    ContentBlock,
    ContentDocument,
    DocumentMeta,
    FormulaBlock,
    HeadingBlock,
    KeyValueBlock,
    ListBlock,
    ListItem,
    ParagraphBlock,
    StepItem,
    StepsBlock,
    TableBlock,
)
from palatium_ai.domain.policies.shape import ShapeRecipePolicy
from palatium_ai.domain.policies.transform import TransformPolicy
from palatium_ai.domain.policies.types import (
    ResponseShape,
    TransformationKind,
)

_KV_SEP: Final[tuple[str, ...]] = (":", "—", "–", "-")


@dataclass(frozen=True, slots=True)
class MechanicalRestructureDecision:
    """Outcome of one mechanical attempt — ``document is None`` means call the LLM."""

    document: ContentDocument | None
    reason: str


class MechanicalRestructurePolicy:
    """Pure policy: reuse / reshape prior blocks without an LLM."""

    @classmethod
    def apply(
        cls,
        prior: ContentDocument | None,
        *,
        shape: ResponseShape | str,
        transformation: TransformationKind | str | None,
        task_kind: str | None = None,
    ) -> MechanicalRestructureDecision:
        if prior is None or not prior.blocks:
            return MechanicalRestructureDecision(None, "no_prior_document")
        if TransformPolicy.needs_reason_over_prior(transformation):
            return MechanicalRestructureDecision(None, "content_transform_needs_llm")

        kind = ShapeRecipePolicy.coerce(shape)
        recipe = ShapeRecipePolicy.resolve(shape=kind, task_kind=task_kind or "knowledge_request")

        if kind == "prose":
            return MechanicalRestructureDecision(
                cls._with_blocks(prior, cls._flatten_to_paragraphs(prior.blocks)),
                "flatten_to_prose",
            )

        if recipe is not None:
            if ShapeRecipePolicy.validate(prior, recipe).satisfied:
                return MechanicalRestructureDecision(prior, "prior_already_satisfies_shape")
            promoted = cls._try_promote(prior, kind)
            if promoted is not None and ShapeRecipePolicy.validate(promoted, recipe).satisfied:
                return MechanicalRestructureDecision(promoted, f"promoted_to_{kind}")
            return MechanicalRestructureDecision(None, "shape_needs_llm")

        # ``auto`` + layout-only restructure: keep substance, let align fill icons/locale.
        if TransformPolicy.coerce(transformation) == "restructure":
            return MechanicalRestructureDecision(prior, "restructure_reuse_prior")
        return MechanicalRestructureDecision(None, "not_eligible")

    @classmethod
    def _try_promote(cls, prior: ContentDocument, shape: ResponseShape) -> ContentDocument | None:
        if shape == "plan":
            steps = cls.promote_emphasized_ordered_lists(prior.blocks)
            if steps is None:
                return None
            return cls._with_blocks(prior, steps)
        if shape == "document_analysis":
            # Cannot invent headings; only pass when structure already exists.
            return None
        if shape == "comparison_table":
            return None
        return None

    @classmethod
    def promote_emphasized_ordered_lists(cls, blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...] | None:
        """Public entry for align/formatter paths — same rules as plan promote."""
        return cls._lists_to_steps(blocks)

    @classmethod
    def _lists_to_steps(cls, blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...] | None:
        """Ordered list with bold emphasis (or ``Title: body`` text) → one StepsBlock."""
        out: list[ContentBlock] = []
        converted = False
        for block in blocks:
            if not isinstance(block, ListBlock) or block.style != "ordered" or len(block.items) < 2:
                out.append(block)
                continue
            items = tuple(step for item in block.items if (step := cls._list_item_as_step(item)) is not None)
            if len(items) < 2:
                out.append(block)
                continue
            out.append(StepsBlock(type="steps", items=items))
            converted = True
        return tuple(out) if converted else None

    @classmethod
    def _list_item_as_step(cls, item: ListItem) -> StepItem | None:
        if (item.emphasis or "").strip():
            return StepItem(title=item.emphasis.strip()[:200], body=(item.text or " ")[:2000])
        for sep in _KV_SEP:
            if sep in item.text:
                title, _, body = item.text.partition(sep)
                title, body = title.strip(), body.strip()
                if title and body:
                    return StepItem(title=title[:200], body=body[:2000])
        return None

    @classmethod
    def _flatten_to_paragraphs(cls, blocks: tuple[ContentBlock, ...]) -> tuple[ContentBlock, ...]:
        paragraphs: list[ParagraphBlock] = []
        for block in blocks:
            for line in _block_lines(block):
                text = line.strip()
                if text:
                    paragraphs.append(ParagraphBlock(text=text[:8000]))
        return tuple(paragraphs) or (ParagraphBlock(text=" "),)

    @classmethod
    def _with_blocks(cls, prior: ContentDocument, blocks: tuple[ContentBlock, ...]) -> ContentDocument:
        meta = prior.meta
        if not isinstance(meta, DocumentMeta):
            meta = DocumentMeta(confidence=0.9)
        return prior.model_copy(update={"blocks": blocks, "actions": (), "meta": meta})


def _block_lines(block: ContentBlock) -> list[str]:
    match block:
        case HeadingBlock(text=text) | ParagraphBlock(text=text):
            return [text]
        case CalloutBlock(title=title, body=body):
            return [*([title] if title else []), body]
        case CodeBlock(content=content) | FormulaBlock(latex=content):
            return [content]
        case ListBlock(items=items):
            return [f"{item.emphasis}: {item.text}" if item.emphasis else item.text for item in items]
        case StepsBlock(items=items):
            return [f"{item.title}: {item.body}" for item in items]
        case KeyValueBlock(items=items):
            return [f"{item.label}: {item.value}" for item in items]
        case TableBlock(columns=columns, rows=rows):
            return [" | ".join(columns), *(" | ".join(row) for row in rows)]
        case _:
            return []


__all__ = ["MechanicalRestructureDecision", "MechanicalRestructurePolicy"]
