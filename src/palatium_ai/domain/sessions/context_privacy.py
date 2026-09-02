"""Session context privacy and control-plane isolation."""

from __future__ import annotations

from collections.abc import Mapping

# Soft bound for session.context keys (not the authoritative user utterance).
SESSION_USER_TEXT_PREVIEW_MAX_CHARS = 256

# Platform-owned keys — never accept from client upsert; redact from public GET.
SERVER_CONTROL_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "quality_revision_count",
        "last_critic_summary",
        "approved_content_sha256",
        "last_user_text",
        "effective_user_text",
        "pending_tool_approval",
        "last_operation",
        "last_task_id",
        "last_task_kind",
        "last_status",
        "last_error",
        "requires_review",
        "requires_mcp",
        "candidate_capabilities",
        "org_id",
    }
)

# Explicit client allow-list (empty = clients cannot write any context key).
CLIENT_WRITABLE_CONTEXT_KEYS: frozenset[str] = frozenset()


def session_user_text_preview(
    text: str,
    *,
    max_chars: int = SESSION_USER_TEXT_PREVIEW_MAX_CHARS,
) -> str:
    """Truncate user text for durable session.context (full text lives in DialogTurnStore)."""
    cleaned = text.strip()
    if max_chars < 1:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars == 1:
        return "…"
    return f"{cleaned[: max_chars - 1]}…"


def filter_client_context_patch(patch: Mapping[str, object] | None) -> dict[str, object]:
    """Keep only client-writable keys; drop control-plane and unknown keys."""
    if not patch:
        return {}
    return {
        key: value
        for key, value in patch.items()
        if key in CLIENT_WRITABLE_CONTEXT_KEYS and key not in SERVER_CONTROL_CONTEXT_KEYS
    }


def public_session_context(context: Mapping[str, object]) -> dict[str, object]:
    """Strip server control-plane keys from API responses."""
    return {key: value for key, value in context.items() if key not in SERVER_CONTROL_CONTEXT_KEYS}
