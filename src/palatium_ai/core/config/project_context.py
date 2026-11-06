# src/palatium_ai/core/config/project_context.py

"""Runtime project context files (CMD2 AGENTS.md) — filesystem SoT."""

from __future__ import annotations

from pydantic import Field

from .base import BaseConfig


class ProjectContextConfig(BaseConfig):
    """Load ``AGENTS.md`` into the stable prompt tier when agents request it."""

    agents_md_enabled: bool = Field(
        default=True,
        validation_alias="PROJECT_AGENTS_MD",
        description="When false, ContextBuilder returns empty project_agents_md.",
    )
    agents_md_path: str = Field(
        default="AGENTS.md",
        min_length=1,
        max_length=512,
        validation_alias="PROJECT_AGENTS_MD_PATH",
        description="Path relative to process cwd (or absolute). Only this basename allowlist in v1.",
    )
    agents_md_max_chars: int = Field(
        default=8_000,
        ge=500,
        le=20_000,
        validation_alias="PROJECT_AGENTS_MD_MAX_CHARS",
    )
