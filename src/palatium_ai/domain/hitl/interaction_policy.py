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
    IconToken,
    KeyValueBlock,
    ListBlock,
    ParagraphBlock,
    StepsBlock,
)
from palatium_ai.domain.content.content_document import KeyValueItem

if TYPE_CHECKING:
    from palatium_ai.domain.content import ContentDocument
    from palatium_ai.domain.mcp.models import ExecutionStrategy


DocumentInteraction = Literal["none", "choice", "confirm"]
PromotedFrom = Literal["actions", "list", "steps", "callouts", "kv", "none"]


def _strategy_value(selected_strategy: ExecutionStrategy | str | None) -> str | None:
    """Normalise a strategy to its raw string value.

    ``ExecutionStrategy`` is a ``Literal[str, ...]`` alias, not an enum, so there is
    no ``.value`` to unwrap — the parameter exists for callers that hold the alias
    and for those that already carry a plain ``str`` (050: one honest shape).
    """
    return selected_strategy


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
    #: Intent tagged a choice on a turn that already answered a read-only ask.
    #: The answer is delivered and no card is minted; the log keeps the cause.
    ignored_user_choice: bool = False


class HitlInteractionPolicy:
    """Pure domain policy: document + flags → HITL card plan."""

    _MAX_PROMOTED_OPTIONS = 12
    _MIN_CHOICE_OPTIONS = 2
    #: Turns whose deliverable *is* the answer about the assistant itself. A
    #: capability or small-talk enumeration is content, not an exclusive menu:
    #: promoting it to a required card swallowed the answer the user asked for
    #: (live UI: «Что ты умеешь?» became "choose one of 5 capabilities").
    _INFORMATIONAL_TASK_KINDS: frozenset[str] = frozenset({"capability_discovery", "social_conversation"})
    #: Explicit ``response_shape`` whose structure *is* the answer body (W10 p1_list).
    #: A catalogue ListBlock must not be rewritten into exclusive HITL options —
    #: that axis lives on Intent ``response_shape``, not phrase lists (055).
    _CATALOGUE_SHAPES: frozenset[str] = frozenset({"inventory", "plan", "document_analysis", "comparison_table", "prose"})

    @classmethod
    def plan(
        cls,
        document: ContentDocument | None,
        *,
        requires_review: bool,
        selected_strategy: ExecutionStrategy | str | None = None,
        task_kind: str | None = None,
        requires_user_choice: bool = False,
        has_turn_attachments: bool = False,
        response_shape: str | None = None,
    ) -> HitlCardPlan:
        """Decide choice card options and whether to mint quality review."""
        if document is None:
            return HitlCardPlan(
                mint_quality_review=False,
                reason="no_document",
            )

        # A choice card is a *clarification*: the turn stops and asks because work
        # cannot proceed. An answered read-only ask (fact, lookup) delivers its
        # document; an over-tagged Intent choice must not turn it into a write-style
        # confirmation menu (E2E-07, 020: HITL is for actions, not reads).
        clarification_turn = cls._is_clarification_turn(selected_strategy, task_kind)
        effective_user_choice = requires_user_choice and clarification_turn
        ignored_user_choice = requires_user_choice and not clarification_turn

        # Upload-grounded turn without an Intent choice axis: do not promote
        # list/steps/actions into exclusive menus (Formatter may echo a prior
        # topic as bullets → fake HITL about the wrong file, 055).
        if has_turn_attachments and not effective_user_choice:
            return HitlCardPlan(
                choice_actions=(),
                mint_quality_review=requires_review,
                reason="attachment_grounds_ask",
                menu_shaped=cls._is_menu_shaped(document),
                promoted_from="none",
                force_structural=False,
                required_choice=False,
                ignored_user_choice=ignored_user_choice,
            )

        # An informational turn (capabilities, small talk) asks to be *told*, not
        # asked to pick: its list is the answer body. Minting it as the only
        # selector hides that answer behind a click nobody requested (020).
        if cls._is_informational_turn(task_kind, effective_user_choice):
            return HitlCardPlan(
                choice_actions=(),
                mint_quality_review=requires_review,
                reason="informational_answer",
                menu_shaped=cls._is_menu_shaped(document),
                promoted_from="none",
                force_structural=False,
                required_choice=False,
                ignored_user_choice=ignored_user_choice,
            )

        # Catalogue / structured deliverable (inventory, plan, …): the ListBlock
        # *is* the answer. Structural menu promotion would strip it into a
        # "Select one of N options" HITL card (live W10 p1_list regression).
        if cls._is_catalogue_deliverable(response_shape, effective_user_choice):
            return HitlCardPlan(
                choice_actions=(),
                mint_quality_review=requires_review,
                reason="catalogue_answer",
                menu_shaped=cls._is_menu_shaped(document),
                promoted_from="none",
                force_structural=False,
                required_choice=False,
                ignored_user_choice=ignored_user_choice,
            )

        menu_shaped = cls._is_menu_shaped(document)
        interaction = getattr(document.meta, "interaction", "none") or "none"
        if (effective_user_choice or menu_shaped) and interaction == "none":
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
                requires_user_choice=effective_user_choice,
                menu_shaped=menu_shaped,
            )

        choice_actions = actions if cls._is_choice_set(actions, interaction=interaction) else ()
        required_choice = cls.requires_choice_mint(
            document,
            selected_strategy=selected_strategy,
            task_kind=task_kind,
            interaction=interaction,
            requires_user_choice=effective_user_choice,
            menu_shaped=menu_shaped,
        )
        force_structural = menu_shaped and not effective_user_choice and interaction in {"choice", "confirm"}
        mint_quality_review = requires_review
        reason = (
            f"interaction={interaction}; choices={len(choice_actions)}; "
            f"review={requires_review}; requires_user_choice={requires_user_choice}; "
            f"clarification_turn={clarification_turn}; "
            f"menu_shaped={menu_shaped}; promoted_from={promoted_from}; "
            f"force_structural={force_structural}; required_choice={required_choice}"
        )

        if not choice_actions and required_choice:
            # Rhetorical interaction=choice on an informational report (e.g. compare
            # ending with "which version?") must not kill a usable answer. Fail-closed
            # only when Intent/structure truly demand exclusive cards.
            if cls._can_downgrade_rhetorical_choice(
                requires_user_choice=effective_user_choice,
                menu_shaped=menu_shaped,
                selected_strategy=selected_strategy,
                task_kind=task_kind,
                interaction=interaction,
            ):
                return HitlCardPlan(
                    choice_actions=(),
                    mint_quality_review=mint_quality_review,
                    reason="interaction_downgraded_informational",
                    menu_shaped=menu_shaped,
                    promoted_from=promoted_from,
                    force_structural=False,
                    required_choice=False,
                    ignored_user_choice=ignored_user_choice,
                )
            return HitlCardPlan(
                choice_actions=(),
                mint_quality_review=False,
                reason="formatter_output_invalid",
                menu_shaped=menu_shaped,
                promoted_from=promoted_from,
                force_structural=force_structural,
                required_choice=True,
                ignored_user_choice=ignored_user_choice,
            )

        return HitlCardPlan(
            choice_actions=choice_actions,
            mint_quality_review=mint_quality_review,
            reason=reason,
            menu_shaped=menu_shaped,
            promoted_from=promoted_from,
            force_structural=force_structural,
            required_choice=required_choice,
            ignored_user_choice=ignored_user_choice,
        )

    @classmethod
    def _is_informational_turn(
        cls,
        task_kind: str | None,
        effective_user_choice: bool,
    ) -> bool:
        """True when the turn must deliver prose/facts, never a blocking selector.

        Only the closed axis decides (055): unknown kinds keep the fail-closed
        structural behaviour, and an explicit clarification choice still wins.
        """
        return task_kind in cls._INFORMATIONAL_TASK_KINDS and not effective_user_choice

    @classmethod
    def _is_catalogue_deliverable(
        cls,
        response_shape: str | None,
        effective_user_choice: bool,
    ) -> bool:
        """True when ``response_shape`` names a body composition, not a picker.

        ``auto`` stays fail-closed (exclusive menus without an Intent shape flag).
        A real clarification choice still wins over shape.
        """
        if effective_user_choice or not response_shape:
            return False
        shape = response_shape.strip().lower()
        return shape in cls._CATALOGUE_SHAPES

    @classmethod
    def _is_clarification_turn(
        cls,
        selected_strategy: ExecutionStrategy | str | None,
        task_kind: str | None,
    ) -> bool:
        """True when the turn exists to ask the user, not to deliver an answer.

        An unclassified turn (``task_kind is None``, e.g. a domain-only caller) is
        treated as a clarification: without a known kind we cannot assert the ask
        was already answered, so the choice contract stays fail-closed.
        """
        _ = cls
        if task_kind is None:
            return True
        return _strategy_value(selected_strategy) == "clarify" or task_kind == "clarification_needed"

    @classmethod
    def _can_downgrade_rhetorical_choice(
        cls,
        *,
        requires_user_choice: bool,
        menu_shaped: bool,
        selected_strategy: ExecutionStrategy | str | None,
        task_kind: str | None,
        interaction: str,
    ) -> bool:
        """True when LLM tagged choice/confirm without a real exclusive menu contract."""
        _ = cls
        if requires_user_choice or menu_shaped:
            return False
        strategy = _strategy_value(selected_strategy)
        if strategy == "clarify" or task_kind == "clarification_needed":
            return False
        return interaction in {"choice", "confirm"}

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
        # Untagged actions are formatter suggestions, not an exclusive pick: minting
        # them as a required choice card blocks an answered turn (D4).
        return interaction == "choice" and len(actions) >= cls._MIN_CHOICE_OPTIONS

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

        icons = cls._exclusive_option_icons(document, source=source, count=len(labels))
        actions = tuple(
            ActionSpec(
                action_id=f"choice_{index}",
                label=label[:200],
                kind="custom",
                style="primary" if index == 0 else "secondary",
                icon=icons[index - 1] if index - 1 < len(icons) else None,
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
        """Keep title/framing; remove exclusive menu blocks (HITL cards own selection)."""
        labels, source = cls._exclusive_option_labels_with_source(document)
        drop_callouts = source == "callouts" and len(labels) >= cls._MIN_CHOICE_OPTIONS
        drop_kv = source == "kv" and len(labels) >= cls._MIN_CHOICE_OPTIONS

        framing: list[object] = []
        for block in document.blocks:
            if isinstance(block, ListBlock | StepsBlock):
                continue
            if drop_callouts and isinstance(block, CalloutBlock):
                continue
            if drop_kv and isinstance(block, KeyValueBlock):
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
        labels, source = cls._exclusive_option_labels_with_source(document)
        if len(labels) < cls._MIN_CHOICE_OPTIONS or len(labels) > cls._MAX_PROMOTED_OPTIONS:
            return False
        framing = 0
        for block in document.blocks:
            if isinstance(block, ListBlock | StepsBlock):
                continue
            if isinstance(block, CalloutBlock):
                # Callout rows are the exclusive options when labels came from them.
                continue
            if source == "kv" and isinstance(block, KeyValueBlock):
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
    def _exclusive_option_icons(
        cls,
        document: ContentDocument,
        *,
        source: PromotedFrom,
        count: int,
    ) -> tuple[IconToken | None, ...]:
        """Preserve row icons when promoting kv/callout menus into HITL actions."""
        _ = cls
        if count <= 0:
            return ()
        pad = tuple(None for _ in range(count))
        if source == "kv":
            kv_blocks = [block for block in document.blocks if isinstance(block, KeyValueBlock)]
            if len(kv_blocks) != 1:
                return pad
            icons = tuple(item.icon for item in kv_blocks[0].items[:count])
            return icons + pad[len(icons) :]
        if source == "callouts":
            callouts = [block for block in document.blocks if isinstance(block, CalloutBlock)]
            icons = tuple(block.icon for block in callouts[:count])
            return icons + pad[len(icons) :]
        return pad

    @staticmethod
    def _choice_label_from_kv_item(item: KeyValueItem) -> str:
        """One option text: drop «Технологии — Технологии и IT» duplication (Big Tech 020)."""
        label = item.label.strip()
        value = item.value.strip()
        if not value:
            return label
        if not label:
            return value
        label_l = label.casefold()
        value_l = value.casefold()
        if value_l == label_l or value_l.startswith(label_l):
            return value
        # Short distinct pairs still pick the human option (value), not the key.
        if len(value) <= 120:
            return value
        return label

    @classmethod
    def _kv_looks_like_choice_menu(cls, items: tuple[KeyValueItem, ...]) -> bool:
        """True for topic pickers; False for data panels (Срок/30 дней, inventory kv)."""
        if len(items) < cls._MIN_CHOICE_OPTIONS or len(items) > cls._MAX_PROMOTED_OPTIONS:
            return False
        expansions = 0
        for item in items:
            if len(item.value.strip()) > 160:
                return False
            label_l = item.label.strip().casefold()
            value_l = item.value.strip().casefold()
            if value_l == label_l or value_l.startswith(label_l):
                expansions += 1
        return expansions >= max(cls._MIN_CHOICE_OPTIONS, (len(items) + 1) // 2)

    @classmethod
    def _exclusive_option_labels_with_source(
        cls,
        document: ContentDocument,
    ) -> tuple[tuple[str, ...], PromotedFrom]:
        """Labels + provenance from a single list/callout/kv menu shape."""
        list_blocks = [block for block in document.blocks if isinstance(block, ListBlock)]
        step_blocks = [block for block in document.blocks if isinstance(block, StepsBlock)]
        kv_blocks = [block for block in document.blocks if isinstance(block, KeyValueBlock)]

        if len(list_blocks) == 1 and not step_blocks and not kv_blocks:
            labels = tuple(item.text.strip() for item in list_blocks[0].items if item.text.strip())
            return labels, "list"
        if len(step_blocks) == 1 and not list_blocks:
            # Steps are a process timeline (howto), not an exclusive picker. Promoting
            # them forced ``formatter_output_invalid`` when Intent did not mint actions
            # (W10 p1_howto). Exclusive choice menus stay on ListBlock / CalloutBlock /
            # KeyValueBlock / explicit ``actions`` (schema also requires non-empty step bodies).
            _ = step_blocks
            return (), "none"

        # Formatter often emits exclusive topics as kv rows (short key + expanded value).
        # Static kv as the only selector violates 020 — promote to HITL cards.
        if len(kv_blocks) == 1 and not list_blocks and not step_blocks and cls._kv_looks_like_choice_menu(kv_blocks[0].items):
            non_framing = [
                block
                for block in document.blocks
                if not isinstance(block, HeadingBlock | ParagraphBlock | DividerBlock | KeyValueBlock)
            ]
            if not non_framing:
                labels = tuple(
                    cls._choice_label_from_kv_item(item)
                    for item in kv_blocks[0].items
                    if item.label.strip() or item.value.strip()
                )
                if cls._MIN_CHOICE_OPTIONS <= len(labels) <= cls._MAX_PROMOTED_OPTIONS:
                    return labels, "kv"

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
            and not kv_blocks
        ):
            return callout_labels, "callouts"
        return (), "none"
