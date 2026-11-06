# src/palatium_ai/domain/skills/product_lock.py

"""Product procedural skills-lock (CMD4) — separate from DX ``skills-lock.json``."""

from __future__ import annotations

import hashlib
import json

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field


class SkillLockEntry(BaseModel):
    """One locked skill: semver + content hash for rollback / drift detection."""

    model_config = {"frozen": True}

    version: str = Field(min_length=1, max_length=32)
    sha256: str = Field(min_length=64, max_length=64)
    updated_at: str = Field(min_length=1, max_length=40)


class ProductSkillsLock(BaseModel):
    """Root document for ``skills/procedural/skills-lock.json``."""

    model_config = {"frozen": True}

    version: int = Field(default=1, ge=1)
    skills: dict[str, SkillLockEntry] = Field(default_factory=dict)


def content_sha256(raw: str) -> str:
    """Stable SHA-256 of UTF-8 skill markdown (normalized newlines)."""
    normalized = raw.replace("\r\n", "\n").encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()


def load_product_lock(path: Path) -> ProductSkillsLock:
    """Load lockfile; missing file → empty lock."""
    if not path.is_file():
        return ProductSkillsLock()
    raw = path.read_text(encoding="utf-8")
    return ProductSkillsLock.model_validate_json(raw)


def write_product_lock(path: Path, lock: ProductSkillsLock) -> None:
    """Atomic rewrite of the product lock (tmp + replace)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = lock.model_dump_json(indent=2) + "\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(path)


def upsert_lock_entry(
    lock: ProductSkillsLock,
    *,
    name: str,
    version: str,
    content: str,
) -> ProductSkillsLock:
    """Return a new lock with ``name`` updated."""
    skills = dict(lock.skills)
    skills[name] = SkillLockEntry(
        version=version,
        sha256=content_sha256(content),
        updated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return ProductSkillsLock(version=lock.version, skills=skills)


def remove_lock_entry(lock: ProductSkillsLock, *, name: str) -> ProductSkillsLock:
    """Return a new lock without ``name`` (no-op if absent)."""
    if name not in lock.skills:
        return lock
    skills = dict(lock.skills)
    skills.pop(name, None)
    return ProductSkillsLock(version=lock.version, skills=skills)


def lock_to_pretty_json(lock: ProductSkillsLock) -> str:
    """Canonical pretty JSON for tests / scripts."""
    return json.dumps(lock.model_dump(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = [
    "ProductSkillsLock",
    "SkillLockEntry",
    "content_sha256",
    "load_product_lock",
    "lock_to_pretty_json",
    "remove_lock_entry",
    "upsert_lock_entry",
    "write_product_lock",
]
