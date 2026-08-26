# tests/unit/test_hitl_email_slack_notifier.py

"""Email / Slack HITL OOB notifiers (port adapters)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

from palatium_ai.domain.hitl.notify import HitlEscalationNotice
from palatium_ai.infrastructure.hitl.email_notifier import EmailHitlNotifier
from palatium_ai.infrastructure.hitl.slack_notifier import SlackHitlNotifier


def _notice() -> HitlEscalationNotice:
    return HitlEscalationNotice(
        card_id="card-1",
        thread_id="th-1",
        task_id="task-1",
        purpose="mcp_tool_approval",
        org_id="org-1",
        risk_score=0.9,
        escalate_to_roles=("manager",),
        reason="ttl_expired",
    )


@pytest.mark.asyncio
async def test_email_notifier_sends_via_smtp() -> None:
    notifier = EmailHitlNotifier(
        host="smtp.example",
        port=587,
        mail_from="hitl@example.com",
        mail_to=("ops@example.com",),
        username="u",
        password="p",  # noqa: S106 — test fixture
        use_tls=True,
    )
    smtp = MagicMock()
    smtp.__enter__.return_value = smtp
    smtp.__exit__.return_value = False
    with patch("palatium_ai.infrastructure.hitl.email_notifier.smtplib.SMTP", return_value=smtp):
        await notifier.notify_escalation(_notice())
    smtp.ehlo.assert_called()
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("u", "p")
    smtp.send_message.assert_called_once()


@pytest.mark.asyncio
async def test_slack_notifier_posts_message(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"ok": True}

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args, kwargs

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            _ = args

        async def post(self, url: str, headers: dict[str, str], json: dict[str, object]) -> _Resp:
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    notifier = SlackHitlNotifier(bot_token="xoxb-test", channel="#hitl")  # noqa: S106
    await notifier.notify_escalation(_notice())
    assert captured["url"].endswith("chat.postMessage")
    assert captured["json"]["channel"] == "#hitl"
    assert "card-1" in str(captured["json"]["text"])
