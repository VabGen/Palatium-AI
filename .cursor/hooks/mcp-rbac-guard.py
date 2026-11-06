#!/usr/bin/env python3
"""beforeMCPExecution — product MCP RBAC (070). IDE plugins pass through.

stdin: Cursor hook JSON {tool_name, server_name, ...}
stdout: {permission: allow|ask|deny, ...}
"""

from __future__ import annotations

import json
import sys

READ_TOOLS = frozenset(
    {
        "search_knowledge",
        "search_memory",
        "explain_belief",
        "memory_audit",
        "graph_query",
        "skill_reference",
        "web_fallback",
        "read_attachment",
    }
)

ASK_TOOLS = frozenset(
    {
        "save_memory",
        "forget_memory",
        "extract_transcript_memories",
        "memory_verify",
        "skill_manage",
        "ingest_document",
    }
)

# Product-runtime MCP only. Everything else = Cursor IDE tooling (Figma, browser, …).
PRODUCT_SERVERS = frozenset({"platform", "edms", "analytics"})


def main() -> int:
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        _emit(
            {
                "permission": "deny",
                "agentMessage": (
                    "mcp-rbac-guard: невалидный JSON на stdin — fail-closed (020)."
                ),
                "userMessage": (
                    "Вызов MCP-инструмента заблокирован: guard безопасности недоступен."
                ),
            }
        )
        return 0

    tool = str(payload.get("tool_name") or "")
    server = str(payload.get("server_name") or "")

    if tool in READ_TOOLS:
        _emit({"permission": "allow"})
        return 0

    if tool in ASK_TOOLS:
        _emit(
            {
                "permission": "ask",
                "agentMessage": (
                    f"Инструмент {tool} требует HITL-подтверждения "
                    "по политике платформы (020)."
                ),
                "userMessage": (
                    f"Агент запрашивает вызов критичного инструмента: {tool}"
                ),
            }
        )
        return 0

    if server not in PRODUCT_SERVERS:
        _emit({"permission": "allow"})
        return 0

    _emit(
        {
            "permission": "deny",
            "agentMessage": (
                f"Инструмент {tool} (сервер {server}) отсутствует в закрытом "
                "перечне 070-mcp-tools.mdc — deny by default."
            ),
            "userMessage": f"Заблокирован вызов неизвестного инструмента: {tool}",
        }
    )
    return 0


def _emit(obj: dict[str, str]) -> None:
    # ASCII-safe JSON: Windows hook runners often decode stdout as cp1251/cp1252.
    sys.stdout.write(json.dumps(obj, ensure_ascii=True, separators=(",", ":")))


if __name__ == "__main__":
    raise SystemExit(main())
