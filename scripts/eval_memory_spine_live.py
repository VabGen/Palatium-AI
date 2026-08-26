#!/usr/bin/env python
"""Run live LongMemEval-lite against the configured LLM.

Usage:
  poetry run python scripts/eval_memory_spine_live.py

Requires a working LLM in env/.env (or ENV_FILE=...).
Sets PALATIUM_LIVE_EVAL=1 and exits non-zero on failure.
"""

from __future__ import annotations

import os
import sys


def main() -> int:
    """Invoke pytest live memory suite; return process exit code."""
    os.environ["PALATIUM_LIVE_EVAL"] = "1"
    try:
        import pytest
    except ImportError:
        print("pytest is required (poetry install --with dev)", file=sys.stderr)
        return 2

    return int(
        pytest.main(
            [
                "tests/eval/test_memory_spine_live.py",
                "-q",
                "--tb=short",
                "-m",
                "live",
            ]
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
