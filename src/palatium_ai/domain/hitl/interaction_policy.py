"""When ContentDocument must become clickable HITL cards (never text menus).

Rule (020): any user choice / confirmation is a server-minted HITL card with
action tokens — never a static numbered list as the only selector.

Structural force (code > LLM): an exclusive menu-shaped document always
requires clickable cards, even when Intent forgot requires_user_choice.
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
PromotedFrom = Literal["actions", "list", "steps", "callouts", "none"]


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
    reason: str = Field(min_length=1, max_length=280)
    menu_shaped: bool = False
    promoted_from: PromotedFrom = "none"
    force_structural: bool = False
    required_choice: bool = False


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
        requires_user_choice: bool = False,
    ) -> HitlCardPlan:
        """Decide choice card options and whether to mint quality review."""
        if document is None:
            return HitlCardPlan(
                mint_quality_review=requires_review,
                reason="no_document",
            )

        menu_shaped = cls._is_menu_shaped(document)
        interaction = getattr(document.meta, "interaction", "none") or "none"
        if (requires_user_choice or menu_shaped) and interaction == "none":
            interaction = "choice"

        promoted_from: PromotedFrom = "none"
        actions = tuple(document.actions)
        if actions:
            promoted_from = "actions"
        else:
            actions, promoted_from = cls._promote_structural_choices(
                document,
                selected_strategy=selected_strategy,
                task_kind=task_kind,
                interaction=interaction,
                requires_user_choice=requires_user_choice,
                menu_shaped=menu_shaped,
            )

        choice_actions = actions if cls._is_choice_set(actions, interaction=interaction) else ()
        required_choice = cls.requires_choice_mint(
            document,
            selected_strategy=selected_strategy,
            task_kind=task_kind,
            interaction=interaction,
            requires_user_choice=requires_user_choice,
            menu_shaped=menu_shaped,
        )
        force_structural = menu_shaped and not requires_user_choice and interaction in {"choice", "confirm"}
        mint_quality_review = requires_review
        reason = (
            f"interaction={interaction}; choices={len(choice_actions)}; "
            f"review={requires_review}; requires_user_choice={requires_user_choice}; "
            f"menu_shaped={menu_shaped}; promoted_from={promoted_from}; "
            f"force_structural={force_structural}; required_choice={required_choice}"
        )

        if not choice_actions and required_choice:
            return HitlCardPlan(
                choice_actions=(),
                mint_quality_review=False,
                reason="formatter_output_invalid",
                menu_shaped=menu_shaped,
                promoted_from=promoted_from,
                force_structural=force_structural,
                required_choice=True,
            )

        return HitlCardPlan(
            choice_actions=choice_actions,
            mint_quality_review=mint_quality_review,
            reason=reason,
            menu_shaped=menu_shaped,
            promoted_from=promoted_from,
            force_structural=force_structural,
            required_choice=required_choice,
        )

    @classmethod
    def requires_choice_mint(
        cls,
        document: ContentDocument,
        *,
        selected_strategy: ExecutionStrategy | str | None,
        task_kind: str | None,
        interaction: str,
        requires_user_choice: bool = False,
        menu_shaped: bool | None = None,
    ) -> bool:
        """Return True when UX contract demands clickable cards (not a text menu)."""
        shaped = cls._is_menu_shaped(document) if menu_shaped is None else menu_shaped
        # Structural force: exclusive menus never stay as the only selector.
        if shaped or requires_user_choice or interaction in {"choice", "confirm"}:
            return True
        strategy = _strategy_value(selected_strategy)
        if strategy == "clarify" or task_kind == "clarification_needed":
            return shaped
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
        requires_user_choice: bool = False,
        menu_shaped: bool = False,
    ) -> tuple[tuple[ActionSpec, ...], PromotedFrom]:
        """Promote exclusive list/steps/callouts to actions when the document is a choice menu."""
        strategy = _strategy_value(selected_strategy)
        explicit = (
            requires_user_choice
            or menu_shaped
            or interaction in {"choice", "confirm"}
            or strategy == "clarify"
            or task_kind == "clarification_needed"
        )
        if not explicit and not menu_shaped:
            return (), "none"

        labels, source = cls._exclusive_option_labels_with_source(document)
        if len(labels) < cls._MIN_CHOICE_OPTIONS or len(labels) > cls._MAX_PROMOTED_OPTIONS:
            return (), "none"

        actions = tuple(
            ActionSpec(
                action_id=f"choice_{index}",
                label=label[:200],
                kind="custom",
                style="primary" if index == 0 else "secondary",
            )
            for index, label in enumerate(labels, start=1)
        )
        return actions, source

    @classmethod
    def document_with_choice_framing(
        cls,
        document: ContentDocument,
        *,
        choice_count: int,
    ) -> ContentDocument:
        """Keep title/framing; remove exclusive menu list/steps/callouts (HITL cards own selection)."""
        labels, source = cls._exclusive_option_labels_with_source(document)
        drop_callouts = source == "callouts" and len(labels) >= cls._MIN_CHOICE_OPTIONS

        framing: list[object] = []
        for block in document.blocks:
            if isinstance(block, ListBlock | StepsBlock):
                continue
            if drop_callouts and isinstance(block, CalloutBlock):
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
        labels, _source = cls._exclusive_option_labels_with_source(document)
        if len(labels) < cls._MIN_CHOICE_OPTIONS or len(labels) > cls._MAX_PROMOTED_OPTIONS:
            return False
        framing = 0
        for block in document.blocks:
            if isinstance(block, ListBlock | StepsBlock):
                continue
            if isinstance(block, CalloutBlock):
                # Callout rows are the exclusive options when labels came from them.
                continue
            if isinstance(block, HeadingBlock | ParagraphBlock | DividerBlock):
                framing += 1
                continue
            return False
        return framing <= 3

    @classmethod
    def _exclusive_option_labels(cls, document: ContentDocument) -> tuple[str, ...]:
        """Labels from a single exclusive option structure."""
        labels, _source = cls._exclusive_option_labels_with_source(document)
        return labels

    @classmethod
    def _exclusive_option_labels_with_source(
        cls,
        document: ContentDocument,
    ) -> tuple[tuple[str, ...], PromotedFrom]:
        """Labels + provenance from a single list/steps/callout menu shape."""
        _ = cls
        list_blocks = [block for block in document.blocks if isinstance(block, ListBlock)]
        step_blocks = [block for block in document.blocks if isinstance(block, StepsBlock)]

        if len(list_blocks) == 1 and not step_blocks:
            labels = tuple(item.text.strip() for item in list_blocks[0].items if item.text.strip())
            return labels, "list"
        if len(step_blocks) == 1 and not list_blocks:
            labels = tuple(item.title.strip() for item in step_blocks[0].items if item.title.strip())
            return labels, "steps"

        # Topic rows often arrive as callouts (icon + title) without a list block.
        callout_labels = tuple(
            (block.title or block.body).strip()
            for block in document.blocks
            if isinstance(block, CalloutBlock) and (block.title or block.body).strip()
        )
        non_framing = [
            block
            for block in document.blocks
            if not isinstance(block, HeadingBlock | ParagraphBlock | DividerBlock | CalloutBlock)
        ]
        if (
            len(callout_labels) >= cls._MIN_CHOICE_OPTIONS
            and len(callout_labels) <= cls._MAX_PROMOTED_OPTIONS
            and not non_framing
            and not list_blocks
            and not step_blocks
        ):
            return callout_labels, "callouts"
        return (), "none"
