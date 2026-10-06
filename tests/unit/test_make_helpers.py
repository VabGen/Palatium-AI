"""The Makefile must not depend on POSIX tools (010, 075, 050).

Three recipes used to shell out to ``awk``/``grep``/``cut``/``tr``: ``help`` (which is the
``DEFAULT_GOAL``, so a bare ``make`` hit it), ``require-key``, and therefore ``models`` /
``test-tier``. On a stock Windows + GNU make setup none of those binaries is on ``PATH`` —
recipes are handed to ``cmd.exe`` — so ``make`` died while printing its own help, and the
key guard failed with "LITELLM_MASTER_KEY not set" while the key was sitting in ``env/.env``.
The declared "cross-platform" contract only held inside Git Bash.

These tests pin the replacement contract, so the POSIX dependency cannot creep back in.
"""

from __future__ import annotations

import functools
import importlib.util
import io
import re
import sys

from pathlib import Path
from typing import cast

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_HELPER_PATH = _REPO_ROOT / "scripts" / "make_helpers.py"
_MAKEFILE = _REPO_ROOT / "Makefile"

# Tools the recipes must not require. `curl` is intentionally absent: it ships with Windows
# 10+ and is genuinely useful for the LiteLLM calls, so it is not a portability hazard.
_POSIX_TOOLS = re.compile(r"\b(awk|grep|sed|cut|tr)\b")


@functools.lru_cache(maxsize=1)
def _load_helper_module():
    """Import ``scripts/make_helpers.py`` once per session.

    Cached on purpose: re-executing it per test re-created the argparse subparsers and
    every module object it holds, and those corpses were still being torn down when
    pytest's capture temp file was collected (a Windows-only ``_TemporaryFileCloser``
    unraisable warning at session teardown, unrelated to the code under test).
    """
    spec = importlib.util.spec_from_file_location("make_helpers", _HELPER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["make_helpers"] = module
    spec.loader.exec_module(module)
    return module


def _recipe_lines() -> list[str]:
    """Makefile lines that actually execute, i.e. not comments."""
    lines = []
    for raw in _MAKEFILE.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(raw)
    return lines


def _target_recipes() -> dict[str, list[str]]:
    """Map target -> its recipe lines.

    Variable assignments and ``ifeq`` blocks are not targets: a target line is
    ``name:`` / ``name::`` without a following ``=`` — that is what keeps ``COMPOSE :=``
    out. Recipes are the tab-indented lines, exactly as make reads them.
    """
    recipes: dict[str, list[str]] = {}
    current: str | None = None
    for raw in _MAKEFILE.read_text(encoding="utf-8").splitlines():
        if raw.startswith("\t"):
            if current is not None:
                recipes[current].append(raw)
            continue
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            current = None
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)\s*::?(?!=)", raw)
        current = match.group(1) if match else None
        if current is not None:
            recipes.setdefault(current, [])
    return recipes


def _raise(exc: BaseException):
    """Build a callable that raises ``exc`` — stand-in for a failing urlopen."""

    def raiser(*args: object, **kwargs: object) -> None:
        raise exc

    return raiser


def test_help_lists_every_documented_target() -> None:
    """`make` with no arguments must print the target list, not an error."""
    mod = _load_helper_module()
    rendered = mod.export_help(_MAKEFILE)

    for target in ("make up ", "make up-full", "make rebuild-app", "make obs-up"):
        assert target in rendered, f"{target!r} missing from the rendered help"


def test_help_aligns_descriptions_and_ignores_undocumented_targets() -> None:
    """Only `##`-annotated targets are listed; internal prerequisites stay hidden."""
    mod = _load_helper_module()
    rendered = mod.export_help(_MAKEFILE)

    assert "make require-key" not in rendered, "require-key is an internal prerequisite"
    descriptions = [line.split("  ", 1)[1] for line in rendered.splitlines() if line.startswith("  make ")]
    assert descriptions, "help rendered no targets at all"
    assert all(desc.strip() for desc in descriptions), "every listed target needs a description"


def test_help_handles_a_makefile_without_annotated_targets(tmp_path: Path) -> None:
    """An unannotated Makefile is a message, not a traceback."""
    mod = _load_helper_module()
    boring = tmp_path / "Makefile"
    boring.write_text("all:\n\t@echo hi\n", encoding="utf-8")

    assert "не найдено" in mod.export_help(boring)


def test_makefile_recipes_require_no_posix_tools() -> None:
    """The regression itself: a `grep`/`awk` in a recipe breaks `make` on Windows."""
    offenders = [line for line in _recipe_lines() if _POSIX_TOOLS.search(line) and "python" not in line]
    assert not offenders, "recipe still depends on a POSIX tool:\n" + "\n".join(offenders)


def test_makefile_normalises_an_empty_env_file_override() -> None:
    """`?=` treats a defined-but-empty environment variable as a deliberate override.

    An exported ``ENV_FILE=`` therefore dropped ``--env-file`` from every recipe, and compose
    then failed on the first ``:?`` secret with a message that pointed nowhere near the cause.
    """
    text = _MAKEFILE.read_text(encoding="utf-8")

    assert "ifeq ($(strip $(ENV_FILE)),)" in text, "an empty ENV_FILE override is not normalised"
    assert "ENV_FILE := env/.env" in text, "the normalisation must not fix the value to a different path"


def test_env_get_parses_quotes_comments_and_blank_lines(tmp_path: Path) -> None:
    """Values may be quoted or followed by an inline comment, as in every env/.env template."""
    mod = _load_helper_module()
    env_file = tmp_path / ".env"
    env_file.write_text(
        '# a comment line\n\nLITELLM_MASTER_KEY="sk-from-quotes"\nPLAIN=bare\nTRAILING=value  # inline note\n',
        encoding="utf-8",
    )

    assert mod.env_get(env_file, "LITELLM_MASTER_KEY") == "sk-from-quotes"
    assert mod.env_get(env_file, "PLAIN") == "bare"
    assert mod.env_get(env_file, "TRAILING") == "value"


def test_env_get_treats_a_missing_key_or_file_as_empty(tmp_path: Path) -> None:
    """Absence is a normal answer here; `require_key` is what turns it into a failure."""
    mod = _load_helper_module()

    assert mod.env_get(tmp_path / "absent.env", "ANY") == ""
    assert mod.env_get(tmp_path, "ANY") == ""


def test_require_key_is_silent_on_success_and_loud_on_failure(tmp_path: Path, capsys) -> None:
    mod = _load_helper_module()
    env_file = tmp_path / ".env"
    env_file.write_text("PRESENT=yes\n", encoding="utf-8")

    assert mod.require_key(env_file, "PRESENT") == 0
    assert "PRESENT" not in capsys.readouterr().out, "a passing guard must not print the secret"

    assert mod.require_key(env_file, "ABSENT") == 1
    err = capsys.readouterr().err
    assert "ABSENT" in err, "the message must name the key"
    assert str(env_file) in err, "the message must name the file the key was read from"


@pytest.mark.parametrize("reachable,expected", ((True, 0), (False, 1)))
def test_verify_endpoints_exit_code_tracks_reachability(monkeypatch, reachable: bool, expected: int) -> None:
    """A check that always exits 0 is useless in a script — the old recipe did exactly that."""
    mod = _load_helper_module()
    monkeypatch.setattr(mod, "_reachable", lambda url, timeout=5.0: reachable)

    assert mod.verify_endpoints() == expected


def test_litellm_request_returns_the_error_body_instead_of_empty(monkeypatch) -> None:
    """`curl -sf` printed nothing on a non-2xx, so failures looked like JSON parse errors."""
    mod = _load_helper_module()
    http_error = mod.urllib.error.HTTPError(
        url="http://localhost:4000/v1/models",
        code=401,
        msg="Unauthorized",
        hdrs=None,
        fp=io.BytesIO(b'{"error": "bad key"}'),
    )
    monkeypatch.setattr(mod.urllib.request, "urlopen", _raise(http_error))

    status, body = mod._litellm_request("/v1/models", "sk-nope")

    assert status == 401
    assert body == {"error": "bad key"}, "the reason must survive, not just the status code"
    # `HTTPError` is a `tempfile._TemporaryFileWrapper`: the body is a temp file, and
    # only `close()` releases it. Without this the GC emits a ResourceWarning, which
    # `filterwarnings = ["error"]` escalates into a flaky failure of an unrelated test.
    assert http_error.fp.closed, "the error body must be released, not handed to the GC (050)"


def test_litellm_request_reports_an_unreachable_gateway(monkeypatch) -> None:
    """A refused connection is a message about LiteLLM, not a traceback from urllib."""
    mod = _load_helper_module()
    monkeypatch.setattr(mod.urllib.request, "urlopen", _raise(OSError("connection refused")))

    status, body = mod._litellm_request("/v1/models", "sk-any")

    assert status == 0
    assert isinstance(body, str)
    assert "unreachable" in body


def test_litellm_chat_sends_a_json_object_not_a_shell_literal(monkeypatch, tmp_path: Path) -> None:
    """The payload must be built as data.

    The old recipe passed ``-d '{"model":…}'``; ``cmd.exe`` does not honour single quotes, so
    the request carried literal quotes and failed while the stack was perfectly healthy.
    """
    mod = _load_helper_module()
    captured: dict[str, object] = {}

    def fake_request(path: str, key: str, payload: dict[str, object] | None = None) -> tuple[int, object]:
        captured["path"] = path
        captured["key"] = key
        captured["payload"] = payload
        return 200, {"ok": True}

    monkeypatch.setattr(mod, "_litellm_request", fake_request)
    env_file = tmp_path / ".env"
    env_file.write_text("LITELLM_MASTER_KEY=sk-from-file\n", encoding="utf-8")

    assert mod.litellm_chat(env_file, "tier-mid", "Say OK") == 0

    payload = captured["payload"]
    assert isinstance(payload, dict), "the payload must be a JSON object, not a string"
    assert payload["model"] == "tier-mid"
    assert payload["messages"] == [{"role": "user", "content": "Say OK"}]
    # 020: the key comes from the env file, never from argv.
    assert captured["key"] == "sk-from-file"
    assert str(tmp_path) not in str(captured["key"])


def test_litellm_targets_refuse_to_call_without_a_key(tmp_path: Path, capsys) -> None:
    """Both targets depend on `require-key`; calling them empty must fail, not 401 quietly."""
    mod = _load_helper_module()
    env_file = tmp_path / ".env"
    env_file.write_text("# no key here\n", encoding="utf-8")

    assert mod.litellm_models(env_file) == 1
    assert mod.litellm_chat(env_file, "tier-mid", "Say OK") == 1
    assert "LITELLM_MASTER_KEY" in capsys.readouterr().err


def test_makefile_targets_do_not_pass_the_key_as_a_command_line_argument() -> None:
    """A bearer token in argv is readable by every process on the host (020)."""
    text = _MAKEFILE.read_text(encoding="utf-8")

    assert "Bearer" not in text, "the Makefile still builds an Authorization header in shell"
    for target in ("models:", "test-tier:"):
        assert target in text


#: GNU make hands every recipe to `cmd.exe` on Windows, so these are as fatal as
#: `awk`/`grep`: they are not shipped with the OS and the recipes cannot fall back.
_POSIX_BUILTINS = re.compile(r"(?<![\w./])(cp|mv|rm|mkdir|sed|awk|grep)(?![\w-])|(?:^|\s)\[\s")
#: Targets that *create or recreate* the api container. Their recipe must expand
#: FULL_FLAGS, because the overlays are part of the api's environment, not decoration.
_API_RECREATING = ("up", "up-full", "rebuild-app")


def test_recipes_do_not_shell_out_to_posix_builtins() -> None:
    """`make init` used to run `[ -f … ]` and `cp`, which cannot work on a stock Windows."""
    offenders = [
        line
        for line in _recipe_lines()
        if line.startswith("\t") and _POSIX_BUILTINS.search(line) and "python" not in line
    ]
    assert not offenders, "recipe still depends on a POSIX builtin:\n" + "\n".join(offenders)


def test_every_api_recreating_target_loads_the_attachment_overlays() -> None:
    """Rebuilding the api without the overlays silently downgrades its backends.

    ``docker-compose.attachments-av.yml`` / ``-s3.yml`` set ``ATTACHMENTS_SCANNER_BACKEND``
    and ``ATTACHMENTS_BLOB_BACKEND`` through ``environment:``, which *beats* the service's
    ``env_file: env/.env``. A `rebuild-app` that skips them therefore recreates a container
    with the AV engine already running but unused — no error, no log, just an unscanned
    upload path (020, runbook §16.8).
    """
    recipes = _target_recipes()

    for target in _API_RECREATING:
        assert target in recipes, f"target {target!r} disappeared from the Makefile"
        recipe = "\n".join(recipes[target])
        creates_containers = "--build" in recipe or "build api" in recipe or "up -d" in recipe
        assert creates_containers, f"{target} no longer creates containers — test needs revisiting"
        assert "$(FULL_FLAGS)" in recipe, (
            f"{target!r} recreates api/mcp without $(FULL_FLAGS): the attachment overlays are "
            "dropped and the API falls back to the dev backends from env/.env"
        )


def test_launch_targets_wait_for_real_health() -> None:
    """Readiness must be waited on by the probe, not by `docker compose up --wait`.

    ``--wait`` cannot be used here: the stack has a one-shot init container
    (``silo-init`` creates the buckets and exits 0) and compose reports any exited
    container as a failure — it rejected a launch in which every service was healthy.
    The probe retries only the checks that are not answering yet, so clamd's up-to-5-minute
    signature load no longer makes `make up` print "FAIL clamav" on a working stack.
    """
    recipes = _target_recipes()

    for target in ("up", "up-full", "rebuild-app"):
        recipe = "\n".join(recipes[target])
        assert "up -d" in recipe, f"{target} no longer launches containers"
        probe_lines = [line for line in recipes[target] if "attachments_probe.py" in line]
        assert probe_lines, f"{target!r} launches containers without probing them"
        assert any("--wait" in line and "--env-file" in line for line in probe_lines), (
            f"{target!r} must wait for readiness through the probe (`--wait SECONDS`)"
        )
        assert "--wait-timeout" not in recipe, (
            f"{target!r} went back to `docker compose up --wait`, which fails on silo-init"
        )


def test_rebuild_app_verifies_only_after_the_waiting_probe() -> None:
    """`verify` has no retry, so it must not run before readiness is settled (075).

    A recreate needs ~60 s here (entrypoint ``alembic upgrade head`` + uvicorn bootstrap).
    With ``verify`` first, ``make rebuild-app`` printed ``API FAIL`` / ``LiteLLM FAIL`` for
    a stack that answered ``/health`` a minute later — and since make stops at the first
    non-zero exit, the recipe aborted *before* the probes that do wait could run. The
    ordering is the whole fix, so it is asserted rather than left to the next edit.
    """
    recipes = _target_recipes()
    recipe = recipes.get("rebuild-app")
    assert recipe, "target 'rebuild-app' disappeared from the Makefile"

    verify_at = [index for index, line in enumerate(recipe) if "make_helpers.py verify" in line]
    wait_at = [index for index, line in enumerate(recipe) if "attachments_probe.py" in line and "--wait" in line]

    assert verify_at, "rebuild-app no longer verifies the endpoints it just restarted"
    assert wait_at, "rebuild-app no longer waits for readiness through the probe"
    assert verify_at[0] > wait_at[0], (
        "`verify` runs before the waiting probe: a cold api start becomes a false "
        "`FAIL` and aborts the recipe before the probes can retry"
    )


def test_launch_targets_probe_the_backends_they_just_started() -> None:
    """A launch that does not report its effective backends cannot be verified (010)."""
    recipes = _target_recipes()

    for target in ("up", "up-full", "rebuild-app"):
        recipe = "\n".join(recipes[target])
        assert "attachments_probe.py" in recipe, (
            f"{target!r} starts the attachment containers without reporting which backends the API will actually use"
        )


def test_the_overlay_files_are_not_auto_loaded() -> None:
    """An overlay that compose picks up on its own would apply to `make attach-up` too.

    The S3 overlay points the API at a store whose container only exists under the
    `attachments-s3` profile, so auto-loading it would recreate the exact crash-loop
    (`ensure_bucket()` at boot) that FULL_FLAGS exists to prevent.
    """
    auto_loaded = {f"{name}.yml" for name in ("docker-compose.override",)}
    for overlay in ("docker-compose.attachments-av.yml", "docker-compose.attachments-s3.yml"):
        assert Path(overlay).is_file()
        assert overlay not in auto_loaded, f"{overlay} would be picked up by every compose run"


def test_init_env_creates_the_file_once_and_keeps_local_secrets(tmp_path: Path) -> None:
    """`make init` on a clone that already has an env file must not clobber it (020)."""
    mod = _load_helper_module()
    template = tmp_path / ".env.example"
    template.write_text("LITELLM_MASTER_KEY=sk-change-me\n", encoding="utf-8")
    env_file = tmp_path / "nested" / ".env"

    assert mod.init_env(env_file, template) == 0
    assert env_file.read_text(encoding="utf-8") == "LITELLM_MASTER_KEY=sk-change-me\n"

    env_file.write_text("LITELLM_MASTER_KEY=sk-real\n", encoding="utf-8")
    assert mod.init_env(env_file, template) == 0
    assert env_file.read_text(encoding="utf-8") == "LITELLM_MASTER_KEY=sk-real\n"

    assert mod.init_env(tmp_path / "other.env", tmp_path / "missing.example") == 1


def _stream(encoding: str = "utf-16") -> io.TextIOWrapper:
    """An in-memory text stream we can inspect byte-for-byte.

    Deliberately *not* installed as ``sys.stdout``: swapping the process' streams
    disturbs pytest's own capture machinery, and the production signature already
    takes them as a parameter.
    """
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding)


def test_align_stdout_with_console_uses_the_console_codepage(monkeypatch) -> None:
    """`make help` printed `Palatium-AI Ч ъюьрнф√:` while every byte it wrote was valid.

    Python's locale encoding is CP1251, ``[Console]::OutputEncoding`` is CP866 (OEM), and
    PowerShell decodes a native command's output with the latter. The helper therefore has
    to ask the console, not the locale — which also keeps a UTF-8 terminal on UTF-8.
    """
    mod = _load_helper_module()
    stream = _stream()
    streams = [stream]

    monkeypatch.setattr(mod, "_console_output_codepage", lambda: 866)
    mod.align_stdout_with_console(streams)
    assert stream.encoding.lower().replace("-", "") == "cp866"

    monkeypatch.setattr(mod, "_console_output_codepage", lambda: 65001)
    mod.align_stdout_with_console(streams)
    assert stream.encoding.lower().replace("-", "") == "cp65001"

    # No console (CI, redirected file) => the stream keeps its locale encoding.
    monkeypatch.setattr(mod, "_console_output_codepage", lambda: 0)
    stream.reconfigure(encoding="utf-16")
    mod.align_stdout_with_console(streams)
    assert stream.encoding.lower().replace("-", "") == "utf16"

    stream.close()


def test_align_streams_degrades_glyphs_the_console_cannot_encode() -> None:
    """CP866 has no em dash: the help header must lose a glyph, not raise from `make`."""
    mod = _load_helper_module()
    stream = _stream("utf-8")

    mod.align_streams("cp866", [stream])
    print("Palatium-AI — команды:", file=stream)
    stream.flush()

    buffer = cast("io.BytesIO", stream.buffer)
    written = buffer.getvalue().decode("cp866")
    assert "Palatium-AI" in written
    assert "команды" in written, "the Cyrillic body must survive the re-encoding"
    assert "—" not in written, "CP866 cannot represent an em dash; it is replaced on purpose"
    stream.close()
