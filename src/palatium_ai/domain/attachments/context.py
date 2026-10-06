# src/palatium_ai/domain/attachments/context.py

"""Turn-scoped, already-fenced attachment blocks (020, 065).

Crossing into a prompt is an explicit, typed act: a block exists only after the
service re-checked the stored content and wrapped it with
``wrap_untrusted_tool_output``. Nothing in the dialog path concatenates raw
attachment text on its own, so the fence cannot be forgotten by a later caller.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field

from palatium_ai.domain.policies.types import UntrustedContentAction


class AttachmentContextBlock(BaseModel):
    """One fenced attachment ready to be appended to a turn's context."""

    model_config = {"frozen": True}

    attachment_id: UUID
    filename: str = Field(min_length=1, max_length=255)
    source: str = Field(min_length=1, max_length=128)
    fenced_text: str
    action: UntrustedContentAction
    page_count: int = Field(default=0, ge=0)


class AttachmentTurnContext(BaseModel):
    """Ordered blocks resolved for one dialog turn."""

    model_config = {"frozen": True}

    blocks: tuple[AttachmentContextBlock, ...] = ()

    @property
    def fenced_text(self) -> str:
        """Blocks joined for a single context slot; empty when nothing was attached."""
        return "\n\n".join(block.fenced_text for block in self.blocks)

    @property
    def attachment_ids(self) -> tuple[UUID, ...]:
        """Ids of the attachments that actually made it into the turn."""
        return tuple(block.attachment_id for block in self.blocks)


__all__ = ["AttachmentContextBlock", "AttachmentTurnContext"]
