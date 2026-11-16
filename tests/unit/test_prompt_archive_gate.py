"""LLM prompt archive stays silent when disabled (prod default)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from palatium_ai.application.agents.harness import _maybe_archive_prompts
from palatium_ai.domain.llm.models import ChatMessage


def test_prompt_archive_noop_when_disabled() -> None:
    settings = MagicMock()
    settings.observability.llm_prompt_archive_enabled = False
    settings.app.environment = "production"
    with (
        patch("palatium_ai.application.agents.harness.get_settings", return_value=settings),
        patch("palatium_ai.application.agents.harness.logger") as logger,
        patch("palatium_ai.application.agents.harness.redact_text") as redact,
    ):
        _maybe_archive_prompts(
            agent_role="researcher",
            messages=[ChatMessage(role="user", content="secret prompt body")],
        )
        redact.assert_not_called()
        logger.info.assert_not_called()
