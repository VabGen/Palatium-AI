# src/palatium_ai/infrastructure/memory/user_scope.py

"""Resolve user_id for memory.entries RLS filter (060)."""

from __future__ import annotations


def resolve_user_id(
    namespace: tuple[str, ...],
    value: dict[str, object] | None = None,
) -> str:
    """Derive tenant user_id from namespace and/or stored value."""
    if len(namespace) >= 2 and namespace[0] == "user":
        return str(namespace[1]).strip()
    if value is not None:
        raw = value.get("user_id")
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    if len(namespace) >= 2 and namespace[0] == "org":
        return f"org:{namespace[1]}"
    if len(namespace) >= 3 and namespace[0] == "chat" and namespace[1] == "thread":
        return f"thread:{namespace[2]}"
    return "system"
