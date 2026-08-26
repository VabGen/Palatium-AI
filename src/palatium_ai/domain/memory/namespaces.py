# src/palatium_ai/domain/memory/namespaces.py

"""Namespace helpers for cross-thread MemoryPort (Tencent-like asset taxonomy lite)."""

from __future__ import annotations


def thread_namespace(thread_id: str) -> tuple[str, ...]:
    """Chat L0–L1: facts scoped to one conversation thread."""
    return ("chat", "thread", thread_id)


def user_namespace(user_id: str) -> tuple[str, ...]:
    """User preferences / durable profile facts."""
    return ("user", user_id)


def org_namespace(org_id: str = "default") -> tuple[str, ...]:
    """Org-level wiki/skills later; default bucket for now."""
    return ("org", org_id)
