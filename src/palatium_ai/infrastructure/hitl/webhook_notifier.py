# src/palatium_ai/infrastructure/hitl/webhook_notifier.py

"""Optional HTTP webhook for HITL escalation (Slack/Teams/PagerDuty-compatible JSON)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.hitl.notify import HitlEscalationNotice

if TYPE_CHECKING:
    from collections.abc import Sequence

    from palatium_ai.domain.hitl.notify import HitlNotifierPort

logger = get_logger(__name__)


class WebhookHitlNotifier:
    """POST escalation notice as JSON to an operator webhook URL."""

    def __init__(self, url: str, *, timeout_seconds: float = 5.0) -> None:
        cleaned = url.strip()
        if not (cleaned.startswith("https://") or cleaned.startswith("http://")):
            raise ValueError("HITL notify webhook URL must be http(s)")
        self._url = cleaned
        self._timeout = max(0.5, float(timeout_seconds))

    async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
        """POST notice payload; raise on transport/HTTP errors for composite metrics."""
        payload = {
            "event": "hitl_card_escalated",
            "card_id": notice.card_id,
            "thread_id": notice.thread_id,
            "task_id": notice.task_id,
            "purpose": notice.purpose,
            "org_id": notice.org_id,
            "risk_score": notice.risk_score,
            "escalate_to_roles": list(notice.escalate_to_roles),
            "reason": notice.reason,
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(self._url, json=payload)
            response.raise_for_status()
        logger.info(
            "hitl.escalation.webhook_ok",
            card_id=notice.card_id,
            status_code=response.status_code,
        )


class CompositeHitlNotifier:
    """Fan-out to multiple notifiers; one failure must not block siblings."""

    def __init__(self, notifiers: Sequence[HitlNotifierPort]) -> None:
        self._notifiers = tuple(notifiers)

    async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
        """Deliver to all channels; log per-channel failures."""
        errors: list[str] = []
        for notifier in self._notifiers:
            try:
                await notifier.notify_escalation(notice)
            except Exception as exc:  # noqa: BLE001 — keep sweep path alive
                name = type(notifier).__name__
                errors.append(f"{name}: {exc}")
                logger.warning(
                    "hitl.escalation.notify_channel_failed",
                    channel=name,
                    card_id=notice.card_id,
                    error=str(exc)[:300],
                )
        if errors and len(errors) == len(self._notifiers):
            raise RuntimeError("; ".join(errors))
