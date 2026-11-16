# src/palatium_ai/domain/memory/clear_payload.py

"""Pending payload for HITL-gated memory clear (W11)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryClearPayload(BaseModel, frozen=True):
    """Stashed until HITL approve; then Medium purge + clear_user_graph enqueue."""

    task_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    org_id: str = Field(default="", max_length=128)
