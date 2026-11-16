"""HITL escalation channel selection — single source for wiring and the hardening gate."""

from __future__ import annotations

from pydantic import SecretStr

from palatium_ai.application.wiring import build_hitl_service
from palatium_ai.core.config.security import SecurityConfig
from palatium_ai.infrastructure.hitl.email_notifier import EmailHitlNotifier
from palatium_ai.infrastructure.hitl.logging_notifier import LoggingHitlNotifier
from palatium_ai.infrastructure.hitl.webhook_notifier import CompositeHitlNotifier

_HMAC = "unit-test-hitl-hmac-key-32bytes!!"


def _security(**overrides: object) -> SecurityConfig:
    base: dict[str, object] = {
        "auth_enabled": True,
        "jwt_algorithm": "HS256",
        "jwt_secret": SecretStr("unit-test-jwt-secret-32-bytes!!!!"),
        "cors_origins": "http://127.0.0.1:8000",
    }
    base.update(overrides)
    return SecurityConfig(**base)


def test_no_external_channel_by_default() -> None:
    assert _security().hitl_notify_external_channels == ()


def test_blank_webhook_url_is_not_a_channel() -> None:
    """Empty string normalizes to None at validation — it must not count as a channel."""
    assert _security(hitl_notify_webhook_url="").hitl_notify_external_channels == ()


def test_webhook_channel() -> None:
    security = _security(hitl_notify_webhook_url="https://hooks.example/hitl")
    assert security.hitl_notify_external_channels == ("webhook",)
    assert security.hitl_notify_webhook_target == "https://hooks.example/hitl"


def test_partial_email_config_is_not_a_channel() -> None:
    """Recipients without host/sender cannot deliver, so they must not satisfy the gate."""
    assert _security(hitl_notify_email_to="ops@example.com").hitl_notify_external_channels == ()
    assert (
        _security(hitl_notify_email_to="ops@example.com", hitl_notify_smtp_host="smtp.example.com").hitl_notify_external_channels
        == ()
    )


def test_email_channel_needs_host_sender_and_recipients() -> None:
    security = _security(
        hitl_notify_email_to="ops@example.com",
        hitl_notify_smtp_host="smtp.example.com",
        hitl_notify_email_from="hitl@example.com",
    )
    assert security.hitl_notify_external_channels == ("email",)


def test_slack_needs_both_token_and_channel() -> None:
    assert _security(hitl_notify_slack_bot_token=SecretStr("xoxb-token")).hitl_notify_external_channels == ()
    both = _security(hitl_notify_slack_bot_token=SecretStr("xoxb-token"), hitl_notify_slack_channel="C123")
    assert both.hitl_notify_external_channels == ("slack",)
    assert both.hitl_notify_slack_target == ("xoxb-token", "C123")


def test_channel_names_are_stable_and_ordered() -> None:
    security = _security(
        hitl_notify_webhook_url="https://hooks.example/hitl",
        hitl_notify_email_to="ops@example.com",
        hitl_notify_smtp_host="smtp.example.com",
        hitl_notify_email_from="hitl@example.com",
        hitl_notify_slack_bot_token=SecretStr("xoxb-token"),
        hitl_notify_slack_channel="C123",
    )
    assert security.hitl_notify_external_channels == ("webhook", "email", "slack")


def test_wiring_builds_exactly_the_channels_the_gate_counts() -> None:
    """Wiring must compose the same channels the hardening gate counts — no drift."""
    security = _security(
        hitl_notify_email_to="ops@example.com",
        hitl_notify_smtp_host="smtp.example.com",
        hitl_notify_email_from="hitl@example.com",
    )
    service = build_hitl_service(
        redis_client=None,
        signing_secret=_HMAC,
        security=security,
        require_shared_store=False,
    )
    # Baseline logging channel is always first; the composed adapters follow it.
    assert isinstance(service._notifier, CompositeHitlNotifier)
    assert tuple(type(channel) for channel in service._notifier._notifiers) == (LoggingHitlNotifier, EmailHitlNotifier)
