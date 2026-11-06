# src/palatium_ai/domain/skills/port.py

"""Skill catalog port — filesystem-backed procedural skills (L5), not medium DB."""

from __future__ import annotations

from typing import Protocol

from palatium_ai.domain.skills.types import SkillReference, SkillSummary


class SkillCatalogPort(Protocol):
    """List summaries for JIT context; load reference on demand via MCP tool."""

    def list_summaries(self) -> tuple[SkillSummary, ...]:
        """Return unique skill cards (name + description); no bodies."""
        ...

    def get_reference(self, name: str) -> SkillReference | None:
        """Load ``reference.md`` when present, else SKILL.md body; None if unknown."""
        ...

    def format_catalog(self, *, max_chars: int) -> str:
        """Compact catalog string for ContextBuilder key ``skill_catalog``."""
        ...


class WritableSkillCatalogPort(SkillCatalogPort, Protocol):
    """Optional write surface for HITL ``skill_manage`` (CMD4). Read-only catalogs omit this."""

    def upsert_skill(self, *, name: str, content: str) -> SkillSummary:
        """Atomically write ``SKILL.md`` under the product root; refresh index + lock."""
        ...

    def delete_skill(self, *, name: str) -> bool:
        """Remove a self-authored skill directory; True when something was deleted."""
        ...

    def invalidate_index(self) -> None:
        """Drop cached index so the next read rescans the filesystem."""
        ...
