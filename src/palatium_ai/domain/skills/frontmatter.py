# src/palatium_ai/domain/skills/frontmatter.py

"""Parse SKILL.md YAML frontmatter (name + description + version)."""

from __future__ import annotations

import re

from typing import NamedTuple

import yaml

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.DOTALL)
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class ParsedSkillFrontmatter(NamedTuple):
    """Validated SKILL.md header plus markdown body (frontmatter stripped)."""

    name: str
    description: str
    version: str
    body: str


def parse_skill_frontmatter(raw: str) -> ParsedSkillFrontmatter:
    """Return parsed skill doc; raises ValueError on invalid skill docs."""
    text = raw.replace("\r\n", "\n")
    match = _FRONTMATTER.match(text)
    if match is None:
        msg = "SKILL.md must start with YAML frontmatter (--- ... ---)"
        raise ValueError(msg)
    meta_raw, body = match.group(1), match.group(2)
    try:
        meta = yaml.safe_load(meta_raw) or {}
    except yaml.YAMLError as exc:
        msg = f"invalid SKILL.md frontmatter: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(meta, dict):
        msg = "SKILL.md frontmatter must be a mapping"
        raise ValueError(msg)
    name = str(meta.get("name", "")).strip()
    description = str(meta.get("description", "")).strip()
    version = str(meta.get("version", "")).strip()
    if not _NAME_RE.match(name):
        msg = "SKILL.md frontmatter.name must match [a-z0-9][a-z0-9_-]{0,63}"
        raise ValueError(msg)
    if not description:
        msg = "SKILL.md frontmatter.description is required"
        raise ValueError(msg)
    if not _VERSION_RE.match(version):
        msg = "SKILL.md frontmatter.version must be semver MAJOR.MINOR.PATCH"
        raise ValueError(msg)
    return ParsedSkillFrontmatter(
        name=name,
        description=description[:500],
        version=version,
        body=body.strip(),
    )


def is_safe_skill_name(name: str) -> bool:
    """True when ``name`` is a legal skill id (no path separators)."""
    return bool(_NAME_RE.match(name.strip()))
