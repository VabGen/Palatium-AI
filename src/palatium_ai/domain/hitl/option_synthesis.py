"""When discrete_choice needs server-side option synthesis (HITL cards).

Code decides *that* options are required; LLM only fills labels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.domain.content import (
    ActionSpec,
    ContentDocument,
    DocumentMeta,
    ParagraphBlock,
)

if TYPE_CHECKING:
    from palatium_ai.domain.agents.intent import UnderspecificationKind
    from palatium_ai.domain.hitl.interaction_policy import HitlCardPlan


class DiscreteChoiceSynthesisPolicy:
    """Pure policy: when to synthesize exclusive options for HITL mint."""

    _MIN = 2
    _MAX = 12

    @classmethod
    def needs_synthesis(
        cls,
        *,
        requires_user_choice: bool,
        underspecification_kind: UnderspecificationKind | str | None,
        plan: HitlCardPlan,
    ) -> bool:
        """Return whether exclusive options must be synthesized for HITL mint."""
        _ = cls
        if underspecification_kind == "open_text":
            return False
        if not requires_user_choice and underspecification_kind != "discrete_choice":
            return False
        return not plan.choice_actions

    @classmethod
    def merge_actions_into_document(
        cls,
        document: ContentDocument | None,
        actions: tuple[ActionSpec, ...],
        *,
        framing_text: str | None = None,
    ) -> ContentDocument:
        """Build/replace document so actions become the exclusive selector."""
        _ = cls
        clean_actions = tuple(actions[: cls._MAX])
        if len(clean_actions) < cls._MIN:
            raise ValueError("synthesized actions must have at least 2 options")

        if document is None:
            locale = "en-US"
            title = "Choose an option"
            confidence = 0.85
        else:
            locale = document.locale
            title = document.title or "Choose an option"
            confidence = document.meta.confidence

        text = (framing_text or "").strip() or (
            document.title if document and document.title else "Select one option to continue."
        )
        # Keep light framing only — cards own the selector.
        framing_blocks = (ParagraphBlock(type="paragraph", text=text[:2000]),)
        meta = DocumentMeta(
            confidence=confidence,
            requires_review=False,
            source_refs=(),
            interaction="choice",
        )
        return ContentDocument(
            schema_version=1,
            locale=locale,
            title=title[:300] if title else "Choose an option",
            blocks=framing_blocks,
            actions=clean_actions,
            meta=meta,
        )
