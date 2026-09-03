# src/palatium_ai/domain/memory/save_payload.py

"""Pending user-initiated memory save (off-graph HITL commit path, 020/070)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class MemorySavePayload(BaseModel):
    """Serialized save_memory arguments awaiting HITL approval."""

    model_config = {"frozen": True}

    task_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    namespace_kind: str = Field(min_length=1, max_length=16)
    scope_id: str = Field(min_length=1, max_length=128)
    entry_key: str = Field(min_length=1, max_length=256)
    value_json: str = Field(min_length=2, max_length=50_000)
    memory_type: str = Field(default="fact", max_length=16)
    org_id: str = Field(default="", max_length=128)
