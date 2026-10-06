# src/palatium_ai/domain/skills/__init__.py

"""Procedural skills domain (L5 progressive disclosure)."""

from palatium_ai.domain.skills.port import SkillCatalogPort
from palatium_ai.domain.skills.types import SkillReference, SkillSummary

__all__ = ["SkillCatalogPort", "SkillReference", "SkillSummary"]
