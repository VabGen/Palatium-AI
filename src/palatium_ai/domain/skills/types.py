# src/palatium_ai/domain/skills/types.py

"""Procedural skill contracts — progressive disclosure (065 / Wave M6)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillSummary(BaseModel):
    """Level-1 card: always eligible for JIT context (name + description only)."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=500)
    version: str = Field(default="0.0.0", max_length=32)
    has_reference: bool = False


class SkillReference(BaseModel):
    """Level-3 payload returned by ``skill_reference`` (reference.md or SKILL body)."""

    model_config = {"frozen": True}

    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(default="reference", max_length=32)
    content: str = Field(min_length=0, max_length=50_000)
    truncated: bool = False
