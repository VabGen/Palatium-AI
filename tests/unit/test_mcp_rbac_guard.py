"""Wave 8: mcp-rbac-guard hook enforces closed 070 tool list (fail-closed)."""

from __future__ import annotations

import functools
import json
import shutil
import subprocess

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HOOK_PATH = _REPO_ROOT / ".cursor" / "hooks" / "mcp-rbac-guard.sh"


_CANDIDATE_BASHES = (
    # PATH first (Linux CI: /bin/bash), then the common Windows Git installations
    # (`C:\Windows\System32\bash.exe` is the WSL relay and exists even when no distro
    # is installed, so it must be probed rather than trusted).
    "bash",
    r"C:\Program Files\Git\bin\bash.exe",
    r"C:\Program Files (x86)\Git\bin\bash.exe",
    r"C:\Program Files\Git\usr\bin\bash.exe",
)


@functools.lru_cache(maxsize=1)
def _usable_bash() -> str | None:
    """First bash that runs a script *and* has the hook's ``jq`` dependency.

    The hook is fail-closed (020): without ``jq`` it denies every call, so allow/ask
    verdicts can only be asserted where bash + jq are actually available. Probing both
    keeps those tests honest instead of asserting a deny that only means "no jq".
    """
    for candidate in _CANDIDATE_BASHES:
        resolved = shutil.which(candidate) if not Path(candidate).is_absolute() else candidate
        if resolved is None or not Path(resolved).exists():
            continue
        probe = subprocess.run(  # noqa: S603
            [resolved, "-c", "command -v jq"],
            capture_output=True,
            check=False,
        )
        if probe.returncode == 0:
            return resolved
    return None


def _run_guard(payload: dict[str, object]) -> dict[str, object]:
    bash = _usable_bash()
    if bash is None:
        pytest.skip("mcp-rbac-guard hook tests require bash + jq (hook is fail-closed without jq)")
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


def test_skill_reference_allowed() -> None:
    result = _run_guard({"tool_name": "skill_reference", "server_name": "platform"})
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
