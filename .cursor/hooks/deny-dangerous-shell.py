#!/usr/bin/env python
"""beforeShellExecution — блокирует деструктивные команды (без jq)."""

from __future__ import annotations

import json
import re
import sys
import threading

DENY_PATTERNS = [
    r"rm\s+-rf\s+/",
    r"git\s+push\s+--force\s+.*(main|master|prod)",
    r"curl\s.*\|\s*bash",
    r"wget\s.*\|\s*sh",
    r":\(\)\{ :\|:& \};:",
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
]

_STDIN_TIMEOUT_SEC = 2.0


def _emit(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def _read_stdin_json(timeout: float) -> dict[str, object] | None:
    """Parse hook stdin JSON; return None on timeout / empty / invalid payload."""
    box: dict[str, object] = {}

    def _reader() -> None:
        try:
            box["payload"] = json.load(sys.stdin)
        except Exception as exc:  # noqa: BLE001
            box["error"] = exc

    thread = threading.Thread(target=_reader, daemon=True)
    thread.start()
    thread.join(timeout=timeout)
    if thread.is_alive():
        return None
    payload = box.get("payload")
    return payload if isinstance(payload, dict) else None


def main() -> None:
    """Block destructive shell commands; always emit a JSON permission decision."""
    payload = _read_stdin_json(_STDIN_TIMEOUT_SEC)
    if payload is None:
        # Cursor failClosed=true: never leave stdout empty if stdin stalls.
        _emit({"permission": "allow"})
        return

    cmd = str(payload.get("command") or "")
    for pattern in DENY_PATTERNS:
        if re.search(pattern, cmd, flags=re.IGNORECASE):
            _emit(
                {
                    "permission": "deny",
                    "agentMessage": (
                        "Команда заблокирована политикой ZeroTrust Agent Platform (деструктивная/опасная операция)."
                    ),
                    "userMessage": f"Заблокирована потенциально опасная команда: {cmd}",
                }
            )
            return

    _emit({"permission": "allow"})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        _emit({"permission": "allow", "agentMessage": f"hook soft-fail: {type(exc).__name__}"})
