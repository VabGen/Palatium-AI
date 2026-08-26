# src/palatium_ai/infrastructure/hitl/logging_notifier.py

"""Stub OOB notifier: structlog + audit event (no email/Slack yet)."""

from __future__ import annotations

from datetime import UTC, datetime

from palatium_ai.core.logging import get_logger
from palatium_ai.core.observability.audit import get_audit_logger
from palatium_ai.domain.hitl.notify import HitlEscalationNotice

logger = get_logger(__name__)


class LoggingHitlNotifier:
    """Records escalation for ops pipelines until a real channel adapter exists."""

    async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
        """Log and audit an escalation notice (stub channel)."""
        logger.warning(
            "hitl.escalation.notify",
            card_id=notice.card_id,
            thread_id=notice.thread_id,
            org_id=notice.org_id,
            purpose=notice.purpose,
            risk_score=notice.risk_score,
            roles=",".join(notice.escalate_to_roles),
            reason=notice.reason,
        )
        await get_audit_logger().append_async(
            timestamp=datetime.now(UTC).isoformat(),
            conversation_id=notice.thread_id,
            event="hitl_escalation_notified",
            metadata={
                "card_id": notice.card_id,
                "task_id": notice.task_id,
                "purpose": notice.purpose,
                "org_id": notice.org_id or "",
                "risk_score": str(notice.risk_score),
                "escalate_to_roles": ",".join(notice.escalate_to_roles),
                "reason": notice.reason[:200],
                "channel": "logging_stub",
            },
        )
