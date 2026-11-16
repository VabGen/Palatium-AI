# src/palatium_ai/core/config/skills.py

"""Procedural skill catalog roots (Wave M6 / 065)."""

from __future__ import annotations

import os

from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import NoDecode

from .base import BaseConfig


class SkillsConfig(BaseConfig):
    """Filesystem roots for product procedural skills (not `.agent/` DX memory).

    ``FilesystemSkillCatalog`` indexes roots once per process — restart after
    editing ``SKILL.md`` / ``reference.md`` (no hot-reload).
    """

    # NoDecode: pydantic-settings JSON-decodes complex envs before validators;
    # SKILLS_ROOTS=skills/procedural (pathsep string) must not require JSON.
    roots: Annotated[tuple[str, ...], NoDecode] = Field(
        default=("skills/procedural",),
        validation_alias="SKILLS_ROOTS",
        description="OS pathsep-separated roots relative to process cwd / absolute.",
    )
    catalog_max_chars: int = Field(
        default=4_000,
        ge=200,
        le=20_000,
        validation_alias="SKILLS_CATALOG_MAX_CHARS",
    )
    reference_max_chars: int = Field(
        default=12_000,
        ge=500,
        le=50_000,
        validation_alias="SKILLS_REFERENCE_MAX_CHARS",
    )
    #: CMD4 — self-authored skills via ``skill_manage`` (HITL + lint). Default off until soak.
    allow_self_authored: bool = Field(
        default=False,
        validation_alias="ALLOW_SELF_AUTHORED_SKILLS",
        description="When false, mcp:platform.skill_manage returns Feature disabled.",
    )
    #: Product lock path (relative to cwd or absolute); separate from DX skills-lock.json.
    product_lock_path: str = Field(
        default="skills/procedural/skills-lock.json",
        min_length=1,
        max_length=512,
        validation_alias="SKILLS_PRODUCT_LOCK_PATH",
    )

    @field_validator("roots", mode="before")
    @classmethod
    def _split_roots(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(os.pathsep) if p.strip()]
            return tuple(parts) if parts else ("skills/procedural",)
        if isinstance(value, list):
            return tuple(str(p).strip() for p in value if str(p).strip())
        return value
