# src/palatium_ai/domain/skills/manage_payload.py

"""Pending HITL payload for ``skill_manage`` (020/070 CMD4)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SkillManageAction = Literal["create", "update", "delete"]


class SkillManagePayload(BaseModel):
    """Serialized skill_manage arguments awaiting HITL approval."""

    model_config = {"frozen": True}

    task_id: str = Field(min_length=1, max_length=128)
    thread_id: str = Field(min_length=1, max_length=128)
    user_id: str = Field(min_length=1, max_length=128)
    action: SkillManageAction
    skill_name: str = Field(min_length=1, max_length=64)
    content: str = Field(default="", max_length=30_000)
    description: str = Field(default="", max_length=500)
    org_id: str = Field(default="", max_length=128)
