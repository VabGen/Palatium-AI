# src/palatium_ai/application/agents/formatter/config.py

"""Formatter AgentConfig + payload/completion budgets (030, 065)."""

from __future__ import annotations

from typing import Literal

from palatium_ai.domain.agents.agent_config import AgentConfig

FORMATTER_CONFIG = AgentConfig(
    name="formatter",
    role="formatter",
    model_tier="small",
    temperature=0.0,
    allowed_tools=(),
    timeout_seconds=60,
    max_retries=3,
    confidence_threshold=0.7,
)

MIN_PIPELINE_CONFIDENCE = 0.7
REVIEW_CONFIDENCE_CAP = 0.5
REPAIR_ERROR_HEAD = 1500
LOCALE_REPAIR_ATTEMPTS = 2

# Progressive disclosure budgets (065) — never dump researcher/critic state.
FORMATTER_SOURCE_MAX_CHARS = 8_000
FORMATTER_DIALOG_MAX_CHARS = 2_000
FORMATTER_DIALOG_PER_TURN_MAX_CHARS = 600
# Attachment fences only when there is no worker final_text (format_only / social+file).
FORMATTER_ATTACHMENT_MAX_CHARS = 6_000
FORMATTER_FAST_PATH_CONFIDENCE = 0.85
# Structure-free prose at or under this size is shown as-is (no Formatter LLM).
# Headings, lists, fences, and title lines still go through the LLM.
FORMATTER_PASSTHROUGH_MAX_CHARS = 600

# ContentDocument JSON needs headroom; live truncations at 512 broke UI.
FORMATTER_MAX_COMPLETION_TOKENS = 4_096
FORMATTER_MIN_COMPLETION_TOKENS = 2_048

# Soft composition bias for the model (prompt playbook) — closed set (010/055).
# plain_text / content_generation / document_generation preserve the source's own
# shape: compiling a joke or a drafted letter into icon sections changes its meaning.
# social_reply: synthesize a short phatic reply — user_text is stimulus, not source prose.
FormatterStyleHint = Literal[
    "brand_sections_icons",
    "restructure_sections_icons",
    "choice_cards",
    "clarify_open",
    "revise_keep_structure",
    "plain_text",
    "content_generation",
    "document_generation",
    "social_reply",
]
