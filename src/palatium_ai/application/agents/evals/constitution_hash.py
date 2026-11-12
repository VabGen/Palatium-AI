# src/palatium_ai/application/agents/evals/constitution_hash.py

"""Pin Constitution + verify-prompt SHA-256 for ADR-0010 (W7.3)."""

from __future__ import annotations

import hashlib
import re

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONSTITUTION_PATH = _REPO_ROOT / "src" / "palatium_ai" / "domain" / "policies" / "constitution.py"
_VERIFY_PROMPT_PATHS: tuple[Path, ...] = (
    _REPO_ROOT / "src" / "palatium_ai" / "application" / "agents" / "critic" / "prompts.py",
)
_ADR_0010 = _REPO_ROOT / "docs" / "adr" / "0010-agents-audit-w1-w6-closure.md"

_HASH_LINE = re.compile(
    r"^constitution_sha256:\s*(?P<c>[0-9a-f]{64})\s*$"
    r"|^verify_prompts_sha256:\s*(?P<v>[0-9a-f]{64})\s*$",
    re.MULTILINE,
)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_concat(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda p: str(p).replace("\\", "/")):
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def constitution_sha256() -> str:
    return _sha256_file(_CONSTITUTION_PATH)


def verify_prompts_sha256() -> str:
    return _sha256_concat(_VERIFY_PROMPT_PATHS)


def prompt_file_version(path: Path) -> str:
    """Short hash for LLM log ``prompt_version`` (W8.7)."""
    return _sha256_file(path)[:16]


def read_adr_0010_hashes() -> tuple[str, str]:
    text = _ADR_0010.read_text(encoding="utf-8")
    constitution = ""
    verify = ""
    for match in _HASH_LINE.finditer(text):
        if match.group("c"):
            constitution = match.group("c")
        if match.group("v"):
            verify = match.group("v")
    if not constitution or not verify:
        msg = "ADR-0010 missing constitution_sha256 / verify_prompts_sha256 pins"
        raise ValueError(msg)
    return constitution, verify


__all__ = [
    "constitution_sha256",
    "prompt_file_version",
    "read_adr_0010_hashes",
    "verify_prompts_sha256",
]
