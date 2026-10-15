#!/usr/bin/env python3
"""Fail CI when raw query= leaks into logs / metric labels / OTel attributes.

Allowlist: scripts/lint_observability.allowlist (one regex path or substring per line).
"""

from __future__ import annotations

import re
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
ALLOWLIST_PATH = ROOT / "scripts" / "lint_observability.allowlist"

CHECKS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"logger\.(info|debug|warning|error)\([^)]*\bquery\s*="),
        "raw query= in logger call",
    ),
    (
        re.compile(r"\.labels\([^)]*\bquery\s*="),
        "raw query= in metric label",
    ),
    (
        re.compile(r"set_attribute\(\s*['\"]query['\"]\s*,"),
        "raw query in OTel attribute",
    ),
]


def _load_allowlist() -> list[str]:
    if not ALLOWLIST_PATH.is_file():
        return []
    lines: list[str] = []
    for raw in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _allowed(path: Path, allow: list[str]) -> bool:
    rel = path.relative_to(ROOT).as_posix()
    return any(token in rel for token in allow)


def main() -> int:
    allow = _load_allowlist()
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        if _allowed(path, allow):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if "query_hash" in line or "query.len_bucket" in line or 'query.hash"' in line:
                continue
            for pattern, msg in CHECKS:
                if pattern.search(line):
                    rel = path.relative_to(ROOT).as_posix()
                    violations.append(f"{rel}:{i}: {msg}: {line.strip()}")
    if violations:
        print("Observability lint failed:", file=sys.stderr)
        for item in violations:
            print(f"  {item}", file=sys.stderr)
        return 1
    print("Observability lint OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
