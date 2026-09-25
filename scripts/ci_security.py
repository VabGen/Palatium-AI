#!/usr/bin/env python
"""CI security baseline: dependency vulnerability audit (SCA).

Runs ``pip-audit`` against the installed environment. Blocking by design: a known
vulnerable dependency must be triaged, not ignored silently.

Triaged advisories go into ``security/pip-audit-ignore.txt`` — one advisory ID per
line, ``#`` comments allowed. Every entry is an explicit, reviewable decision.

Static-analysis (bandit) rules are already enforced by ruff's ``S`` selector in
``scripts/ci_quality.py``; running a second tool for the same class of findings would
be duplicate tooling (050).
"""

from __future__ import annotations

import subprocess
import sys

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_IGNORE_FILE = _ROOT / "security" / "pip-audit-ignore.txt"


def _load_ignored_vulns() -> list[str]:
    """Advisory IDs explicitly triaged as accepted risk."""
    if not _IGNORE_FILE.exists():
        return []
    ids: list[str] = []
    for line in _IGNORE_FILE.read_text(encoding="utf-8").splitlines():
        entry = line.split("#", 1)[0].strip()
        if entry:
            ids.append(entry)
    return ids


def main() -> int:
    """Run pip-audit with the triage allowlist; non-zero on untriaged findings."""
    ignored = _load_ignored_vulns()
    argv = ["poetry", "run", "pip-audit"]
    for vuln_id in ignored:
        argv += ["--ignore-vuln", vuln_id]

    print("== pip-audit (SCA) ==")
    if ignored:
        print(f"triaged (accepted risk): {', '.join(ignored)}")
    else:
        print(f"no triaged advisories ({_IGNORE_FILE.relative_to(_ROOT).as_posix()} is empty)")

    completed = subprocess.run(argv, cwd=_ROOT, check=False)  # noqa: S603
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)
    print("ci_security: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
