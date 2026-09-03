"""Wave 8: mcp-rbac-guard hook enforces closed 070 tool list (fail-closed)."""

from __future__ import annotations

import json
import shutil
import subprocess

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".cursor" / "hooks" / "mcp-rbac-guard.sh"


def _run_guard(payload: dict[str, object]) -> dict[str, object]:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash required for mcp-rbac-guard hook tests")
    completed = subprocess.run(  # noqa: S603
        [bash, str(_HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_canonical_read_tool_allowed() -> None:
    result = _run_guard({"tool_name": "search_knowledge", "server_name": "platform"})
    assert result["permission"] == "allow"


def test_search_memory_allowed() -> None:
    result = _run_guard({"tool_name": "search_memory", "server_name": "platform"})
    assert result["permission"] == "allow"


def test_save_memory_requires_ask() -> None:
    result = _run_guard({"tool_name": "save_memory", "server_name": "platform"})
    assert result["permission"] == "ask"


def test_graph_query_allowed() -> None:
    result = _run_guard({"tool_name": "graph_query", "server_name": "platform"})
    assert result["permission"] == "allow"


def test_web_fallback_allowed() -> None:
    result = _run_guard({"tool_name": "web_fallback", "server_name": "platform"})
    assert result["permission"] == "allow"


def test_canonical_write_tool_requires_ask() -> None:
    result = _run_guard({"tool_name": "ingest_document", "server_name": "platform"})
    assert result["permission"] == "ask"


def test_external_edms_tool_denied_by_default() -> None:
    """EDMS stubs are app-runtime tools; Cursor MCP hook stays on canonical 070 list."""
    result = _run_guard({"tool_name": "search_documents", "server_name": "edms"})
    assert result["permission"] == "deny"


def test_unknown_tool_denied() -> None:
    result = _run_guard({"tool_name": "delete_everything", "server_name": "edms"})
    assert result["permission"] == "deny"
