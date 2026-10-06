# src/palatium_ai/application/services/feedback_service.py

"""Persist assistant-message like/dislike (web-embed §5 п.17)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.feedback.models import FeedbackAction, FeedbackUpsertResult

if TYPE_CHECKING:
    from palatium_ai.domain.ports.feedback import MessageFeedbackPort

logger = get_logger(__name__)


class FeedbackService:
    """Thin use-case over MessageFeedbackPort."""

    def __init__(self, repository: MessageFeedbackPort) -> None:
        self._repository = repository

    async def submit(
        self,
        *,
        user_id: str,
        message_id: str,
        action: FeedbackAction,
        thread_id: str | None = None,
        org_id: str | None = None,
    ) -> FeedbackUpsertResult:
        if action == "clear":
            result = await self._repository.clear(user_id=user_id, message_id=message_id)
        else:
            result = await self._repository.upsert(
                user_id=user_id,
                message_id=message_id,
                rating=action,
                thread_id=thread_id,
                org_id=org_id,
            )
        logger.info(
            "feedback.submitted",
            user_id=user_id,
            message_id=message_id,
            action=action,
            status=result.status,
            org_id=org_id,
            thread_id=thread_id,
        )
        return result
