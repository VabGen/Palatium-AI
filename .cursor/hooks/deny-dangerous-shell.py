#!/usr/bin/env python
"""BeforeShellExecution — блокирует деструктивные команды (без jq)."""

from __future__ import annotations

import contextlib
import json
import re
import sys
import threading

from pathlib import Path

_HOOKS_ROOT = Path(__file__).resolve().parent
if str(_HOOKS_ROOT) not in sys.path:
    sys.path.insert(0, str(_HOOKS_ROOT))
from lib import audit_chain  # noqa: E402

DENY_PATTERNS: list[str] = [
    r"rm\s+-rf\s+/",
    r"git\s+push\s+.*--force",
    r"curl\s.*\|\s*bash",
    r"wget\s.*\|\s*sh",
    r":\(\)\{ :\|:& \};:",
    r"DROP\s+TABLE",
    r"DROP\s+DATABASE",
]

_PROTECTED_BRANCHES: re.Pattern[str] = re.compile(r"(main|master|prod|production)")
_STDIN_TIMEOUT_SEC: float = 2.0


def _emit(payload: dict[str, object]) -> None:
    """Write JSON payload to stdout and flush."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()


def _deny(cmd: str, reason: str) -> None:
    """Log denied command and emit deny permission."""
    audit_chain.append_event("shell_command_denied", {"command": cmd, "reason": reason})
    _emit(
        {
            "permission": "deny",
            "agentMessage": (
                f"Команда заблокирована политикой ZeroTrust Agent Platform ({reason})."
            ),
            "userMessage": f"Заблокирована потенциально опасная команда: {cmd}",
        }
    )


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
        audit_chain.append_event(
            "shell_hook_stdin_timeout",
            {"timeout_sec": _STDIN_TIMEOUT_SEC},
        )
        _emit(
            {
                "permission": "deny",
                "agentMessage": (
                    "beforeShellExecution: не удалось прочитать payload за таймаут — "
                    "fail-closed (020)."
                ),
                "userMessage": (
                    "Команда заблокирована: guard не смог проверить её безопасность вовремя."
                ),
            }
        )
        return

    cmd = str(payload.get("command") or "")

    for pattern in DENY_PATTERNS:
        if re.search(pattern, cmd, flags=re.IGNORECASE):
            reason = "деструктивная/опасная операция"
            if "push" in pattern and _PROTECTED_BRANCHES.search(cmd) is None:
                continue
            _deny(cmd, reason)
            return

    _emit({"permission": "allow"})


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        with contextlib.suppress(Exception):
            audit_chain.append_event(
                "shell_hook_crashed",
                {"exception": type(exc).__name__, "message": str(exc)},
            )
        _emit(
            {
                "permission": "deny",
                "agentMessage": (
                    f"beforeShellExecution упал ({type(exc).__name__}) — "
                    "fail-closed по failClosed=true (020)."
                ),
                "userMessage": "Команда заблокирована: guard безопасности завершился с ошибкой.",
            }
        )
