# src/palatium_ai/domain/policies/subagent_context.py

"""Fresh context by default — child agents get handoff payload, not parent dump (W7.1).

``context_ratio`` is a **regression guard** on size drift (ADR-0011). Isolation proof
is structural: child context keys ⊆ allow-list and ∩ pollution keys = ∅.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

#: Explicit handoff payload keys (ADR-0009 § Handoff payload) — closed allow-list.
ALLOWED_HANDOFF_CONTEXT_KEYS: Final[frozenset[str]] = frozenset(
    {
        "context_packet_json",
        "prior_context",
        "prior_assistant_content",
        "revision_feedback",
        "dialog_window_json",
        "memory_hints_json",
        "execution_plan_json",
        "skill_catalog",
        "mcp_tool_output_max_chars",
        # Graph / tenant meta (not a parent transcript dump).
        "_task_id",
        "_thread_id",
        "_user_id",
        "_org_id",
        "_parent_role",
        "_parent_context_chars",
    }
)

#: Keys that smuggle parent transcript / tool dumps into a child (fail-closed).
FORBIDDEN_PARENT_DUMP_KEYS: Final[frozenset[str]] = frozenset(
    {
        "parent.messages",
        "parent_messages",
        "messages",
        "full_transcript",
        "raw_parent_context",
        # Parent tool / worker pollution (isolation, not size).
        "tool_results",
        "parent_tool_results",
        "worker_tool_results",
        "mcp_tool_results",
        "tool_calls",
        "parent_tool_calls",
    }
)


def context_char_len(context: Mapping[str, str] | None) -> int:
    if not context:
        return 0
    return sum(len(k) + len(v) for k, v in context.items())


def context_ratio(*, child_chars: int, parent_chars: int) -> float:
    """Size drift ratio — regression guard only, not isolation proof (ADR-0011)."""
    if parent_chars <= 0:
        return 0.0
    return child_chars / parent_chars


def forbidden_dump_keys(context: Mapping[str, str]) -> list[str]:
    """Pollution keys present in child context (empty = clean of hard-forbidden dumps)."""
    return sorted(k for k in context if k in FORBIDDEN_PARENT_DUMP_KEYS)


def keys_outside_handoff_allowlist(context: Mapping[str, str]) -> list[str]:
    """Keys not on the closed handoff allow-list (isolation proof, W7.1)."""
    return sorted(k for k in context if k not in ALLOWED_HANDOFF_CONTEXT_KEYS)


def assert_fresh_handoff_context(context: Mapping[str, str]) -> list[str]:
    """Return isolation violations: forbidden dumps or keys outside allow-list."""
    return sorted(set(forbidden_dump_keys(context)) | set(keys_outside_handoff_allowlist(context)))


__all__ = [
    "ALLOWED_HANDOFF_CONTEXT_KEYS",
    "FORBIDDEN_PARENT_DUMP_KEYS",
    "assert_fresh_handoff_context",
    "context_char_len",
    "context_ratio",
    "forbidden_dump_keys",
    "keys_outside_handoff_allowlist",
]
