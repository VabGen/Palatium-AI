# scripts/verify_audit_chain.py
"""Daily (or on-demand) hash-chain integrity check for the audit log (040).

Exit codes:
  0 — chain OK (or empty log)
  1 — integrity errors found
  2 — configuration / IO failure
"""

from __future__ import annotations

import argparse
import sys

from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Palatium audit hash chain")
    parser.add_argument(
        "--file",
        default="",
        help="Audit log path (default: AUDIT_LOG_FILE env or .cursor/logs/audit-chain.log)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional max records to verify from the end of the file",
    )
    args = parser.parse_args(argv)

    from palatium_ai.core.observability.audit import AuditChainLogger, get_audit_logger

    logger = AuditChainLogger(file_path=Path(args.file.strip())) if args.file.strip() else get_audit_logger()

    try:
        errors = logger.verify_chain(limit=args.limit)
    except OSError as exc:
        print(f"audit-chain: IO failure: {exc}", file=sys.stderr)
        return 2

    if not errors:
        print(f"audit-chain: OK ({logger.file_path})")
        return 0

    print(f"audit-chain: CRITICAL — {len(errors)} error(s) in {logger.file_path}", file=sys.stderr)
    for err in errors[:50]:
        print(f"  - {err}", file=sys.stderr)
    if len(errors) > 50:
        print(f"  … {len(errors) - 50} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
