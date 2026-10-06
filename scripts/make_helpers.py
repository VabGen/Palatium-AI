"""Makefile helpers — portable replacements for POSIX pipelines (010, 050).

Why this exists: the Makefile's recipes used ``awk``/``grep``/``cut``/``tr`` for two
jobs — printing the target list and reading ``LITELLM_MASTER_KEY`` out of the env file.
On a stock Windows + GNU make setup none of those tools is on ``PATH`` (verified: the
recipes are handed to ``cmd.exe``), so ``make`` with no arguments died in ``help``, and
``require-key`` saw an empty key and refused the ``models``/``test-tier`` targets. The
declared "cross-platform" contract was therefore only true inside Git Bash.

Python is already the one interpreter every entry point in this repo depends on
(``scripts/menu.ps1`` and the Makefile both shell out to it), so both helpers live here
and the Makefile carries no POSIX dependency at all.

Usage:
  python scripts/make_helpers.py help
  python scripts/make_helpers.py init-env [--env-file env/.env]
  python scripts/make_helpers.py env-get LITELLM_MASTER_KEY [--env-file env/.env]
  python scripts/make_helpers.py require-key LITELLM_MASTER_KEY
  python scripts/make_helpers.py verify
  python scripts/make_helpers.py models [--env-file env/.env]
  python scripts/make_helpers.py chat --model tier-mid [--prompt "Say OK"]
"""

from __future__ import annotations

import argparse
import ctypes
import io
import json
import re
import shutil
import sys
import urllib.error
import urllib.request

from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import cast

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_MAKEFILE = _REPO_ROOT / "Makefile"
_DEFAULT_ENV_FILE = _REPO_ROOT / "env" / ".env"
_DEFAULT_ENV_TEMPLATE = _REPO_ROOT / "env" / ".env.example"
# `up: ## Собрать и запустить` — the `##` suffix is the documented help convention.
_TARGET_RE = re.compile(r"^([A-Za-z0-9_-]+):[^#\n]*##\s*(?P<desc>.*)$")
_HELP_HEADER = "Palatium-AI — команды:"


def _console_output_codepage() -> int:
    """Return the console's output codepage, or 0 when there is no console."""
    if sys.platform != "win32":
        return 0  # pragma: no cover - Windows-only path
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # pragma: no cover - Windows-only
    return int(kernel32.GetConsoleOutputCP())  # pragma: no cover - Windows-only


def align_streams(encoding: str, streams: Iterable[io.TextIOWrapper] | None = None) -> None:
    """Re-encode ``streams`` (default: the process' stdout/stderr) into ``encoding``."""
    for stream in _default_streams() if streams is None else streams:
        current = (stream.encoding or "").lower().replace("-", "")
        if current != encoding.lower().replace("-", ""):
            stream.reconfigure(encoding=encoding, errors="replace")


def align_stdout_with_console(streams: Iterable[io.TextIOWrapper] | None = None) -> None:
    """Emit in the *console* codepage, not the locale one.

    On Windows the two disagree by default — ``GetConsoleOutputCP()`` is CP866 (OEM)
    while Python's locale encoding is CP1251 — and PowerShell decodes a native
    command's output with ``[Console]::OutputEncoding``. So the Cyrillic help arrived
    as ``Palatium-AI Ч ъюьрнф√:`` even though every byte Python wrote was valid.

    Only the byte encoding changes, and it is read from the console itself, so a
    UTF-8 terminal (``chcp 65001``) keeps getting UTF-8. Redirected output (CI logs,
    files) is left alone: no console, no codepage, no change.
    """
    codepage = _console_output_codepage()
    if codepage:
        align_streams(f"cp{codepage}", streams)


def _default_streams() -> Iterator[io.TextIOWrapper]:
    """The process' own output streams, typed as the concrete wrappers they are."""
    yield cast("io.TextIOWrapper", sys.stdout)
    yield cast("io.TextIOWrapper", sys.stderr)


def export_help(makefile: Path) -> str:
    """Render the ``##`` help of every target, aligned for a terminal."""
    entries: list[tuple[str, str]] = []
    for line in makefile.read_text(encoding="utf-8").splitlines():
        match = _TARGET_RE.match(line)
        if match is not None:
            target = line.split(":", 1)[0]
            entries.append((target, match.group("desc").strip()))

    if not entries:
        return f"{_HELP_HEADER}\n\n  (не найдено ни одной цели с `##`)"

    width = max(len(target) for target, _ in entries)
    lines = [_HELP_HEADER, ""]
    lines += [f"  make {target.ljust(width)}  {desc}" for target, desc in entries]
    return "\n".join(lines)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=value`` lines: comments, blanks and surrounding quotes dropped.

    Deliberately not python-dotenv: this runs from ``make`` before the virtualenv that
    would hold the app's dependencies is guaranteed to exist, so it must stay stdlib-only.
    """
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.split(" #", 1)[0].strip().strip('"').strip("'")
    return values


def env_get(env_file: Path, key: str) -> str:
    """Return one value from the env file, or an empty string when absent.

    An empty result is a legitimate answer, not an error: the caller's own guard
    (``require-key``) turns it into the operator-facing message.
    """
    return _parse_env_file(env_file).get(key, "")


def init_env(env_file: Path, template: Path) -> int:
    """`make init` — create the env file from the template, never overwrite it.

    Replaces ``[ -f X ] || (cp T X && echo)``: ``[`` and ``cp`` are POSIX, and GNU make
    hands recipes to ``cmd.exe`` on Windows, so a fresh clone could not be initialised
    at all. An existing file is left untouched on purpose — it holds local secrets (020).
    """
    if env_file.is_file():
        print(f"• {env_file} уже существует — не перезаписываю")
        return 0
    if not template.is_file():
        print(f"❌ шаблон {template} не найден", file=sys.stderr)
        return 1
    env_file.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template, env_file)
    print(f"✅ {env_file} создан из {template.name}")
    return 0


def require_key(env_file: Path, key: str) -> int:
    """Fail loudly when a required key is absent — the `require-key` prerequisite.

    Replaces ``[ -n "$(KEY)" ] || { …; }``, which is POSIX shell: GNU make hands recipes
    to ``cmd.exe`` on Windows, where both ``[`` and ``{`` are "not recognized as an
    internal or external command", so the guard could never pass there.
    """
    if env_get(env_file, key):
        return 0
    print(f"❌ {key} not set in {env_file}", file=sys.stderr)
    return 1


#: Same set the menu's "Check endpoints" uses, and the ones the docs list per profile.
_HEALTH_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ("API", "http://localhost:8000/health"),
    ("LiteLLM", "http://localhost:4000/health/liveliness"),
    ("MCP EDMS", "http://localhost:8080/health"),
    ("MCP Analytics", "http://localhost:8081/health"),
)


def _reachable(url: str, timeout: float = 5.0) -> bool:
    """True for any 2xx; a refused socket is a FAIL, not an exception."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return 200 <= int(response.status) < 300
    except Exception:
        return False


def verify_endpoints() -> int:
    """Report every health endpoint and exit non-zero if any is down.

    A check that always exits 0 cannot be used in a script, which is what "verify"
    promises; the previous ``curl … && echo || echo`` recipe always succeeded.
    """
    failed = 0
    for name, url in _HEALTH_ENDPOINTS:
        ok = _reachable(url)
        failed += 0 if ok else 1
        print(f"  {name:<14}  {'OK' if ok else 'FAIL'}")
    return 1 if failed else 0


#: LiteLLM's own health/metrics surface lives on 4000 (see docs/runbook.md §5).
_LITELLM_BASE_URL = "http://localhost:4000"


def _litellm_request(path: str, key: str, payload: dict[str, object] | None = None) -> tuple[int, object]:
    """Call LiteLLM and return ``(status, decoded_body)``; never raise on HTTP errors.

    The error body is returned rather than swallowed: ``curl -sf`` printed *nothing* on a
    non-2xx, so the old recipes surfaced as ``Expecting value: line 1 column 1`` from
    ``json.tool`` — a parse error that named neither the status nor the reason.
    """
    url = f"{_LITELLM_BASE_URL}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 - fixed loopback URL, no user input
        url,
        data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="GET" if data is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:  # noqa: S310
            return int(response.status), json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # `HTTPError` is a `tempfile._TemporaryFileWrapper` subclass: the body lives in a
        # temporary file that only `close()` releases. Leaving it to the GC raises
        # "ResourceWarning: Implicitly cleaning up <HTTPError …>", which `filterwarnings =
        # ["error"]` turns into a nondeterministic suite failure (050: resources are freed).
        code = int(exc.code)
        try:
            body = exc.read().decode("utf-8", errors="replace")
        finally:
            exc.close()
        try:
            return code, json.loads(body)
        except json.JSONDecodeError:
            return code, body
    except OSError as exc:
        return 0, f"LiteLLM unreachable at {_LITELLM_BASE_URL}: {exc}"


def litellm_models(env_file: Path) -> int:
    """`make models` — list the tier models without putting the key in argv.

    The key is read from the env file rather than passed as a flag: an argv value is
    visible to every process on the host, and the Makefile recipe cannot avoid that
    while shell-quoting is the thing being fixed (020).
    """
    key = env_get(env_file, "LITELLM_MASTER_KEY")
    if not key:
        return require_key(env_file, "LITELLM_MASTER_KEY")

    status, body = _litellm_request("/v1/models", key)
    print(json.dumps(body, indent=2, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


def litellm_chat(env_file: Path, model: str, prompt: str) -> int:
    """`make test-tier` — one real completion, which is what the target promises.

    Built as a JSON payload in Python instead of a shell literal: ``-d '{"model":…}'``
    relies on single quotes, which ``cmd.exe`` does not honour, so the request went out
    with literal quotes and the target failed while the stack was perfectly healthy.
    """
    key = env_get(env_file, "LITELLM_MASTER_KEY")
    if not key:
        return require_key(env_file, "LITELLM_MASTER_KEY")

    payload: dict[str, object] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    status, body = _litellm_request("/v1/chat/completions", key, payload)
    print(json.dumps(body, indent=2, ensure_ascii=False))
    return 0 if 200 <= status < 300 else 1


def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI.

    Every option hangs off its own subcommand instead of the root parser: a Makefile
    recipe naturally writes ``env-get KEY --env-file …``, and argparse would reject a
    root-level ``--env-file`` placed *after* the subcommand.
    """
    parser = argparse.ArgumentParser(description="Makefile helpers (no POSIX tooling required).")
    subparsers = parser.add_subparsers(dest="command", required=True)

    help_parser = subparsers.add_parser("help", help="print the `##` help of every Makefile target")
    help_parser.add_argument("--makefile", default=str(_DEFAULT_MAKEFILE), help="Makefile to scan")

    env_get_parser = subparsers.add_parser("env-get", help="print one KEY from the env file")
    env_get_parser.add_argument("key", help="variable name, e.g. LITELLM_MASTER_KEY")
    env_get_parser.add_argument("--env-file", default=str(_DEFAULT_ENV_FILE), help="env file to read")

    require_parser = subparsers.add_parser("require-key", help="exit 1 when KEY is unset or empty")
    require_parser.add_argument("key", help="variable name that must be present")
    require_parser.add_argument("--env-file", default=str(_DEFAULT_ENV_FILE), help="env file to read")

    subparsers.add_parser("verify", help="GET every health endpoint and report OK/FAIL")

    init_parser = subparsers.add_parser("init-env", help="create the env file from the template")
    init_parser.add_argument("--env-file", default=str(_DEFAULT_ENV_FILE), help="env file to create")
    init_parser.add_argument(
        "--template",
        default=str(_DEFAULT_ENV_TEMPLATE),
        help="template to copy when the env file is missing",
    )

    models_parser = subparsers.add_parser("models", help="list LiteLLM tier models")
    models_parser.add_argument("--env-file", default=str(_DEFAULT_ENV_FILE), help="env file to read")

    chat_parser = subparsers.add_parser("chat", help="one real completion through LiteLLM")
    chat_parser.add_argument("--model", default="tier-mid", help="tier alias to call")
    chat_parser.add_argument("--prompt", default="Say OK", help="user message to send")
    chat_parser.add_argument("--env-file", default=str(_DEFAULT_ENV_FILE), help="env file to read")

    return parser


def main(argv: list[str] | None = None) -> int:
    align_stdout_with_console()
    args = _build_parser().parse_args(argv)

    if args.command == "help":
        print(export_help(Path(args.makefile)))
        return 0

    if args.command == "env-get":
        print(env_get(Path(args.env_file), args.key))
        return 0

    if args.command == "require-key":
        return require_key(Path(args.env_file), args.key)

    if args.command == "verify":
        return verify_endpoints()

    if args.command == "init-env":
        return init_env(Path(args.env_file), Path(args.template))

    if args.command == "models":
        return litellm_models(Path(args.env_file))

    if args.command == "chat":
        return litellm_chat(Path(args.env_file), args.model, args.prompt)

    return 2  # pragma: no cover - argparse rejects unknown subcommands first


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
