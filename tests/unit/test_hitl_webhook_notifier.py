"""Webhook + composite HITL notifier adapters."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from palatium_ai.domain.hitl.notify import HitlEscalationNotice
from palatium_ai.infrastructure.hitl.logging_notifier import LoggingHitlNotifier
from palatium_ai.infrastructure.hitl.webhook_notifier import (
    CompositeHitlNotifier,
    WebhookHitlNotifier,
)


def _notice() -> HitlEscalationNotice:
    return HitlEscalationNotice(
        card_id="hitl_abc",
        thread_id="th-1",
        task_id="task-1",
        purpose="mcp_tool_approval",
        org_id="org-1",
        risk_score=0.9,
        escalate_to_roles=("manager",),
        reason="high_risk_timeout",
    )


@pytest.mark.asyncio
async def test_webhook_notifier_posts_json(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    class _Resp:
        status_code = 204

        def raise_for_status(self) -> None:
            return None

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            _ = args, kwargs

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> None:
            _ = args

        async def post(self, url: str, json: dict[str, object]) -> _Resp:
            calls.append({"url": url, "json": json})
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    notifier = WebhookHitlNotifier("https://hooks.example/hitl", timeout_seconds=2.0)
    await notifier.notify_escalation(_notice())
    assert len(calls) == 1
    assert calls[0]["url"] == "https://hooks.example/hitl"
    assert calls[0]["json"]["card_id"] == "hitl_abc"
    assert calls[0]["json"]["event"] == "hitl_card_escalated"


@pytest.mark.asyncio
async def test_composite_continues_after_one_failure() -> None:
    ok_calls = 0

    class _Ok:
        async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
            nonlocal ok_calls
            _ = notice
            ok_calls += 1

    class _Boom:
        async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
            _ = notice
            raise RuntimeError("webhook down")

    composite = CompositeHitlNotifier([_Boom(), _Ok(), LoggingHitlNotifier()])
    await composite.notify_escalation(_notice())
    assert ok_calls == 1
