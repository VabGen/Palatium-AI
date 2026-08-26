"""When ContentDocument must become clickable HITL cards (never text menus).

Rule (020): any user choice / confirmation is a server-minted HITL card with
action tokens — never a static numbered list as the only selector.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from palatium_ai.domain.content import (
    ActionSpec,
    CalloutBlock,
    DividerBlock,
    HeadingBlock,
    ListBlock,
    ParagraphBlock,
    StepsBlock,
)

if TYPE_CHECKING:
    from palatium_ai.domain.content import ContentDocument
    from palatium_ai.domain.mcp.models import ExecutionStrategy


DocumentInteraction = Literal["none", "choice", "confirm"]


def _strategy_value(selected_strategy: ExecutionStrategy | str | None) -> str | None:
    if selected_strategy is None:
        return None
    if isinstance(selected_strategy, str):
        return selected_strategy
    return selected_strategy.value


class HitlCardPlan(BaseModel):
    """Which HITL cards the server must mint for one formatter result."""

    model_config = {"frozen": True}

    choice_actions: tuple[ActionSpec, ...] = ()
    mint_quality_review: bool = False
    reason: str = Field(min_length=1, max_length=200)


class HitlInteractionPolicy:
    """Pure domain policy: document + flags → HITL card plan."""

    _MAX_PROMOTED_OPTIONS = 12
    _MIN_CHOICE_OPTIONS = 2

    @classmethod
    def plan(
        cls,
        document: ContentDocument | None,
        *,
        requires_review: bool,
        selected_strategy: ExecutionStrategy | str | None = None,
        task_kind: str | None = None,
    ) -> HitlCardPlan:
        """Decide choice card options and whether to mint quality review."""
        if document is None:
            return HitlCardPlan(
                mint_quality_review=requires_review,
                reason="no_document",
            )

        interaction = getattr(document.meta, "interaction", "none") or "none"
        actions = tuple(document.actions)
        if not actions:
            actions = cls._promote_structural_choices(
                document,
                selected_strategy=selected_strategy,
                task_kind=task_kind,
                interaction=interaction,
            )

        choice_actions = actions if cls._is_choice_set(actions, interaction=interaction) else ()
        mint_quality_review = requires_review
        reason = f"interaction={interaction}; choices={len(choice_actions)}; review={requires_review}"

        if not choice_actions and cls.requires_choice_mint(
            document,
            selected_strategy=selected_strategy,
            task_kind=task_kind,
            interaction=interaction,
        ):
            return HitlCardPlan(
                choice_actions=(),
                mint_quality_review=False,
                reason="formatter_output_invalid",
            )

        return HitlCardPlan(
            choice_actions=choice_actions,
            mint_quality_review=mint_quality_review,
            reason=reason,
        )

    @classmethod
    def requires_choice_mint(
        cls,
        document: ContentDocument,
        *,
        selected_strategy: ExecutionStrategy | str | None,
        task_kind: str | None,
        interaction: str,
    ) -> bool:
        """Return True when UX contract demands clickable cards (not a text menu)."""
        if interaction in {"choice", "confirm"}:
            return True
        strategy = _strategy_value(selected_strategy)
        if strategy == "clarify" or task_kind == "clarification_needed":
            return cls._is_menu_shaped(document)
        return False

    @classmethod
    def _is_choice_set(
        cls,
        actions: tuple[ActionSpec, ...],
        *,
        interaction: str,
    ) -> bool:
        if interaction == "confirm" and len(actions) >= 1:
            return True
        if interaction == "choice" and len(actions) >= cls._MIN_CHOICE_OPTIONS:
            return True
        # Explicit actions without interaction tag still become clickable cards.
        return len(actions) >= cls._MIN_CHOICE_OPTIONS

    @classmethod
    def _promote_structural_choices(
        cls,
        document: ContentDocument,
        *,
        selected_strategy: ExecutionStrategy | str | None,
        task_kind: str | None,
        interaction: str,
    ) -> tuple[ActionSpec, ...]:
        """Promote exclusive list/steps to actions when the document is a choice menu."""
        strategy = _strategy_value(selected_strategy)
        explicit = interaction in {"choice", "confirm"} or strategy == "clarify" or task_kind == "clarification_needed"
        if not explicit and not cls._is_menu_shaped(document):
            return ()

        labels = cls._exclusive_option_labels(document)
        if len(labels) < cls._MIN_CHOICE_OPTIONS or len(labels) > cls._MAX_PROMOTED_OPTIONS:
            return ()

        return tuple(
            ActionSpec(
                action_id=f"choice_{index}",
                label=label[:200],
                kind="custom",
                style="primary" if index == 0 else "secondary",
            )
            for index, label in enumerate(labels, start=1)
        )

    @classmethod
    def document_with_choice_framing(
        cls,
        document: ContentDocument,
        *,
        choice_count: int,
    ) -> ContentDocument:
        """Keep title/framing; remove exclusive menu list/steps (HITL cards own selection)."""
        _ = cls
        framing: list[object] = []
        for block in document.blocks:
            if isinstance(block, ListBlock | StepsBlock):
                continue
            framing.append(block)
        if not framing:
            framing.append(
                ParagraphBlock(
                    type="paragraph",
                    text=f"Select one of the {choice_count} options below.",
                )
            )
        meta = document.meta.model_copy(update={"interaction": "choice"})
        return document.model_copy(
            update={
                "blocks": tuple(framing),
                "actions": (),
                "meta": meta,
            }
        )

    @classmethod
    def _is_menu_shaped(cls, document: ContentDocument) -> bool:
        """Return True when primary content is one exclusive option list plus light framing."""
        labels = cls._exclusive_option_labels(document)
        if len(labels) < cls._MIN_CHOICE_OPTIONS or len(labels) > cls._MAX_PROMOTED_OPTIONS:
            return False
        framing = 0
        for block in document.blocks:
            if isinstance(block, ListBlock | StepsBlock):
                continue
            if isinstance(block, HeadingBlock | ParagraphBlock | CalloutBlock | DividerBlock):
                framing += 1
                continue
            return False
        return framing <= 3

    @classmethod
    def _exclusive_option_labels(cls, document: ContentDocument) -> tuple[str, ...]:
        """Labels from a single list/steps block (exclusive menu shape)."""
        _ = cls
        list_blocks = [block for block in document.blocks if isinstance(block, ListBlock)]
        step_blocks = [block for block in document.blocks if isinstance(block, StepsBlock)]

        if len(list_blocks) == 1 and not step_blocks:
            return tuple(item.text.strip() for item in list_blocks[0].items if item.text.strip())
        if len(step_blocks) == 1 and not list_blocks:
            return tuple(item.title.strip() for item in step_blocks[0].items if item.title.strip())
        return ()
