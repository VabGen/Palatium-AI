# src/palatium_ai/infrastructure/hitl/email_notifier.py

"""SMTP email channel for HITL escalation OOB notify."""

from __future__ import annotations

import asyncio
import smtplib

from email.message import EmailMessage

from palatium_ai.core.logging import get_logger
from palatium_ai.domain.hitl.notify import HitlEscalationNotice

logger = get_logger(__name__)


class EmailHitlNotifier:
    """Send escalation mail via SMTP (stdlib; runs in a worker thread)."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        mail_from: str,
        mail_to: tuple[str, ...] | list[str],
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        timeout_seconds: float = 10.0,
    ) -> None:
        cleaned_host = host.strip()
        if not cleaned_host:
            raise ValueError("HITL_NOTIFY_SMTP_HOST must not be empty")
        recipients = tuple(addr.strip() for addr in mail_to if addr.strip())
        if not recipients:
            raise ValueError("HITL_NOTIFY_EMAIL_TO must list at least one recipient")
        sender = mail_from.strip()
        if not sender or "@" not in sender:
            raise ValueError("HITL_NOTIFY_EMAIL_FROM must be a valid address")
        if port < 1 or port > 65535:
            raise ValueError("HITL_NOTIFY_SMTP_PORT out of range")
        self._host = cleaned_host
        self._port = int(port)
        self._from = sender
        self._to = recipients
        self._username = (username or "").strip() or None
        self._password = password or ""
        self._use_tls = use_tls
        self._timeout = max(1.0, float(timeout_seconds))

    async def notify_escalation(self, notice: HitlEscalationNotice) -> None:
        """Compose and send a short escalation email."""
        message = EmailMessage()
        message["Subject"] = f"[HITL escalated] {notice.purpose} {notice.card_id}"
        message["From"] = self._from
        message["To"] = ", ".join(self._to)
        roles = ",".join(notice.escalate_to_roles) if notice.escalate_to_roles else "-"
        message.set_content(
            "\n".join(
                [
                    f"card_id: {notice.card_id}",
                    f"thread_id: {notice.thread_id}",
                    f"task_id: {notice.task_id}",
                    f"purpose: {notice.purpose}",
                    f"org_id: {notice.org_id or '-'}",
                    f"risk_score: {notice.risk_score}",
                    f"escalate_to_roles: {roles}",
                    f"reason: {notice.reason}",
                ]
            )
        )
        await asyncio.to_thread(self._send, message)
        logger.info("hitl.escalation.email_ok", card_id=notice.card_id, recipients=len(self._to))

    def _send(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as smtp:
            smtp.ehlo()
            if self._use_tls:
                smtp.starttls()
                smtp.ehlo()
            if self._username is not None:
                smtp.login(self._username, self._password)
            smtp.send_message(message)
