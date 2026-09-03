# src/palatium_ai/domain/memory/forget_payload.py

"""Pending user-initiated memory forget (off-graph HITL commit path, 020/070)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemoryForgetPayload(BaseModel):
    """Serialized forget_memory arguments awaiting HITL approval."""

    model_config = {"frozen": True}

    task_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    namespace_kind: str = Field(min_length=1, max_length=16)
    scope_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(min_length=1, max_length=256)
    org_id: str = Field(default="", max_length=128)
