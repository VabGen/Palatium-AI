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
from palatium_ai.domain.policies.locale import ReplyLocalePolicy

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
        has_turn_attachments: bool = False,
    ) -> bool:
        """Return whether exclusive options must be synthesized for HITL mint.

        Fenced uploads already ground summarize/extract asks — synthesizing a
        menu from a prior-topic rewrite would mint cards about the wrong file (055).
        """
        _ = cls
        if has_turn_attachments:
            return False
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
        locale: str | None = None,
    ) -> ContentDocument:
        """Build/replace document so actions become the exclusive selector."""
        _ = cls
        clean_actions = tuple(actions[: cls._MAX])
        if len(clean_actions) < cls._MIN:
            raise ValueError("synthesized actions must have at least 2 options")

        if document is None:
            resolved = ReplyLocalePolicy.normalize(locale) or "und"
            title = framing_text.strip()[:300] if framing_text and framing_text.strip() else None
            confidence = 0.85
        else:
            resolved = document.locale
            title = document.title
            confidence = document.meta.confidence

        text = (framing_text or "").strip() or (document.title if document and document.title else "…")
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
            locale=resolved,
            title=title[:300] if title else None,
            blocks=framing_blocks,
            actions=clean_actions,
            meta=meta,
        )
