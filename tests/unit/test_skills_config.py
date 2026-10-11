"""SkillsConfig — SKILLS_ROOTS is pathsep text, not JSON (dotenv boot)."""

from __future__ import annotations

import os

from palatium_ai.core.config.skills import SkillsConfig


def test_skills_roots_accepts_plain_path_string() -> None:
    cfg = SkillsConfig(SKILLS_ROOTS="skills/procedural")
    assert cfg.roots == ("skills/procedural",)


def test_skills_roots_splits_on_os_pathsep() -> None:
    joined = os.pathsep.join(["skills/procedural", "skills/extra"])
    cfg = SkillsConfig(SKILLS_ROOTS=joined)
    assert cfg.roots == ("skills/procedural", "skills/extra")


def test_skills_roots_empty_falls_back_to_default() -> None:
    cfg = SkillsConfig(SKILLS_ROOTS="  ")
    assert cfg.roots == ("skills/procedural",)
