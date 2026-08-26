# src/palatium_ai/infrastructure/hitl/slack_notifier.py

"""Slack Web API channel for HITL escalation OOB notify."""

from __future__ import annotations

import httpx

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.hitl.notify import HitlEscalationNotice

logger = get_logger(__name__)

_SLACK_POST_MESSAGE = "https://slack.com/api/chat.postMessage"


class SlackHitlNotifier:
    """Post escalation notice via Slack bot token (chat.postMessage)."""

    def __init__(
        self,
        *,
        bot_token: str,
        channel: str,
        timeout_seconds: float = 5.0,
    ) -> None:
        token = bot_token.strip()
        if not token:
            raise ValueError("HITL_NOTIFY_SLACK_BOT_TOKEN must not be empty")
        dest = channel.strip()
        if not dest:
            raise ValueError("HITL_NOTIFY_SLACK_CHANNEL must not be empty")
        self._token = token
        self._channel = dest
        self._timeout = max(0.5, float(timeout_seconds))

    async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
        """POST chat.postMessage; raise when Slack returns ok=false or HTTP error."""
        roles = ", ".join(notice.escalate_to_roles) if notice.escalate_to_roles else "-"
        text = (
            f"*HITL escalated* `{notice.purpose}`\n"
            f"card=`{notice.card_id}` thread=`{notice.thread_id}` "
            f"risk={notice.risk_score} roles=`{roles}`\n"
            f"{notice.reason}"
        )
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json; charset=utf-8",
        }
        payload = {"channel": self._channel, "text": text}
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(_SLACK_POST_MESSAGE, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict) or body.get("ok") is not True:
            err = body.get("error") if isinstance(body, dict) else "invalid_response"
            raise RuntimeError(f"slack chat.postMessage failed: {err}")
        logger.info("hitl.escalation.slack_ok", card_id=notice.card_id, channel=self._channel)
