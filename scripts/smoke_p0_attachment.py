"""C.2 smoke: P0 attachment isolation + recall kind-gate regression suite.

Runs offline (pytest) — no live API. Use after merge of P0-A/P0-B into ``dev``.

Usage:
  uv run python scripts/smoke_p0_attachment.py
  uv run python scripts/smoke_p0_attachment.py --out docs/diagnostics/p0/C2_smoke_post_merge.txt
"""

from __future__ import annotations

import argparse
import subprocess
import sys

from datetime import UTC, datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_TARGETS = (
    "tests/unit/test_p0_get_many_thread_isolation.py",
    "tests/unit/test_attachment_repository.py",
    "tests/unit/test_memory_recall.py",
    "tests/integration/test_p0_attachment_turn_isolation.py",
    "tests/integration/test_p0_dialog_prior_attachment.py",
    "tests/integration/test_p0_scratchpad_leak_to_attachment.py",
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=_ROOT / "docs" / "diagnostics" / "p0" / "C2_smoke_post_merge.txt",
        help="Write full pytest output here",
    )
    args = parser.parse_args()
    cmd = [
        sys.executable,
        "-m",
        "pytest",
        *_TARGETS,
        "-q",
        "--tb=line",
    ]
    print("C.2 smoke:", " ".join(cmd), flush=True)
    proc = subprocess.run(  # noqa: S603 - literal argv list, no shell, no untrusted input
        cmd,
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = (
        f"C.2 smoke_p0_attachment — {stamp}\n"
        f"cwd={_ROOT}\n"
        f"exit={proc.returncode}\n"
        f"cmd={' '.join(cmd)}\n"
        f"{'=' * 72}\n"
        f"{proc.stdout}\n"
        f"{proc.stderr}\n"
    )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body, encoding="utf-8")
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    print(f"wrote {args.out} (exit={proc.returncode})", flush=True)
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
