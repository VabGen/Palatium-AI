# src/palatium_ai/core/config/skills.py

"""Procedural skill catalog roots (Wave M6 / 065)."""

from __future__ import annotations

import os

from pydantic import Field, field_validator

from .base import BaseConfig


class SkillsConfig(BaseConfig):
    """Filesystem roots for product procedural skills (not `.agent/` DX memory).

    ``FilesystemSkillCatalog`` indexes roots once per process — restart after
    editing ``SKILL.md`` / ``reference.md`` (no hot-reload).
    """

    roots: tuple[str, ...] = Field(
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

    @field_validator("roots", mode="before")
    @classmethod
    def _split_roots(cls, value: object) -> object:
        if isinstance(value, str):
            parts = [p.strip() for p in value.split(os.pathsep) if p.strip()]
            return tuple(parts) if parts else ("skills/procedural",)
        if isinstance(value, list):
            return tuple(str(p).strip() for p in value if str(p).strip())
        return value
