# src/palatium_ai/domain/ports/feedback.py

"""Port for persisting message feedback."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.feedback.models import FeedbackRating, FeedbackUpsertResult


class MessageFeedbackPort(Protocol):
    """Upsert or clear a user's rating for one message_id."""

    async def upsert(
        self,
        *,
        user_id: str,
        message_id: str,
        rating: FeedbackRating,
        thread_id: str | None = None,
        org_id: str | None = None,
    ) -> FeedbackUpsertResult:
        """Store like/dislike (replace previous rating for the same pair)."""
        ...

    async def clear(self, *, user_id: str, message_id: str) -> FeedbackUpsertResult:
        """Remove the rating row if present."""
        ...
