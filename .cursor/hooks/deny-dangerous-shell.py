#!/usr/bin/env python
"""BeforeShellExecution — блокирует деструктивные команды (без jq)."""

from __future__ import annotations

import contextlib
import json
import re
import sys

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
            "agentMessage": (f"Команда заблокирована политикой ZeroTrust Agent Platform ({reason})."),
            "userMessage": f"Заблокирована потенциально опасная команда: {cmd}",
        }
    )


def _read_stdin_json() -> dict[str, object] | None:
    """Parse hook stdin JSON. Cursor sends one JSON object then closes stdin."""
    try:
        raw = sys.stdin.read()
    except Exception:  # noqa: BLE001
        return None
    if not raw or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def main() -> None:
    """Block destructive shell commands; always emit a JSON permission decision."""
    payload = _read_stdin_json()
    if payload is None:
        # Infra glitch: ask user rather than hard-deny every command (broken timeout thread
        # previously fail-closed all Shell including git/pytest).
        audit_chain.append_event("shell_hook_stdin_unavailable", {})
        _emit(
            {
                "permission": "ask",
                "agentMessage": "beforeShellExecution: stdin payload missing — ask user to approve.",
                "userMessage": "Guard не получил описание команды. Разрешить выполнение вручную?",
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
                "permission": "ask",
                "agentMessage": (
                    f"beforeShellExecution упал ({type(exc).__name__}) — ask user (не silent deny)."
                ),
                "userMessage": "Guard безопасности завершился с ошибкой. Разрешить команду вручную?",
            }
        )
