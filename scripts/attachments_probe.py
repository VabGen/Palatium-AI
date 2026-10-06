"""Attachments stack probe: object store, AV engine, API, and S3 image preflight.

Usage:
  poetry run python scripts/attachments_probe.py                # all reachable checks
  poetry run python scripts/attachments_probe.py --preflight-image
  poetry run python scripts/attachments_probe.py --s3 --clamav
  poetry run python scripts/attachments_probe.py --mode         # which backend the API uses
  poetry run python scripts/attachments_probe.py --compose-args # flags for a full-stack `up`
  poetry run python scripts/attachments_probe.py --mode --full  # ...and the backends it wires
  poetry run python scripts/attachments_probe.py --wait 300     # block until the stack answers

Why this exists: the attachment pipeline is fail-closed, so a wrong address shows up
as ``quarantined``/``scan_failed`` rows rather than an error at boot. This script
turns "uploads do not work" into the one component that is actually down, and it
gives the Makefile and ``scripts/menu.ps1`` a single implementation to call instead
of two drifting copies of the same checks (010).

``--preflight-image`` is separate from a plain ``docker compose up`` on purpose: a
registry-side failure (denied manifest, missing tag) otherwise surfaces as a confusing
compose error. The preflight names the real cause, and the image it checks is read back
out of docker-compose.yml, so it always validates the container the stack will run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_ENV_FILE = "env/.env"
# Fallback only: the authoritative store image is read back from docker-compose.yml by
# ``resolve_store_image()``. This constant exists so ``--preflight-image`` still works
# when docker/compose cannot be consulted (the probe is wired into `make` and must not
# hard-fail on a machine without a daemon).
_FALLBACK_STORE_IMAGE = (
    "pgsty/silo:RELEASE.2026-09-16T00-00-00Z@sha256:635197cb9f36d01bee221d34d1c7d7960f6a95c48b0b6c01d99cd13bdae51a46"
)
_DEFAULT_MINIO_ENDPOINT = "localhost:9000"
_DEFAULT_CLAMAV_HOST = "localhost"
_DEFAULT_CLAMAV_PORT = 3310
_DEFAULT_API_URL = "http://127.0.0.1:8000"

#: One-shot bucket bootstrap (compose service ``silo-init``). It must exit 0: the API
#: creates its own bucket at startup, but Langfuse does not, so a failed bootstrap
#: leaves ``langfuse`` missing and v3 ingestion stays *silently* empty (020).
_SILO_INIT_SERVICE = "silo-init"

# Compose files a full-stack `up` must name explicitly. `docker-compose.override.yml`
# carries the dev profile split (api behind docker-api, MCP behind docker-mcp), and
# compose only auto-loads it when no `-f` is passed — so the moment we pass any `-f`,
# leaving it out would silently change which services exist.
_BASE_COMPOSE_FILE = "docker-compose.yml"
_PROFILE_COMPOSE_FILE = "docker-compose.override.yml"
_AV_COMPOSE_FILE = "docker-compose.attachments-av.yml"
_S3_COMPOSE_FILE = "docker-compose.attachments-s3.yml"


# Mirror `core/config/attachments.py` when the key is absent from the env file: these are
# the pydantic defaults the app falls back to, so reporting anything else would lie.
_SETTINGS_DEFAULT_BLOB_BACKEND = "memory"
_SETTINGS_DEFAULT_SCANNER_BACKEND = "disabled"
_SETTINGS_DEFAULT_IMAGE_OCR_BACKEND = "auto"

#: Gap between readiness re-checks; a fixed short poll, not a fixed sleep (075): every
#: iteration re-runs the real probe, so a stack that is already up returns immediately.
_RETRY_DELAY_SECONDS = 3.0


def _read_env_file(path: Path) -> dict[str, str]:
    """Parse ``KEY=value`` lines, dropping comments, blanks and surrounding quotes.

    Deliberately not python-dotenv: this script must run before the virtualenv that
    holds the app's dependencies is guaranteed to exist (it is wired into `make`).
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


@dataclass
class Probe:
    """One named check and its outcome; failures carry the operator's next step."""

    name: str
    ok: bool
    detail: str
    hint: str = ""


@dataclass
class Report:
    probes: list[Probe] = field(default_factory=list)

    @property
    def failed(self) -> list[Probe]:
        return [probe for probe in self.probes if not probe.ok]

    def as_dict(self) -> dict[str, object]:
        return {
            "failed": len(self.failed),
            "probes": [
                {"check": probe.name, "ok": probe.ok, "detail": probe.detail, "hint": probe.hint}
                for probe in self.probes
            ],
        }


def run_until_ready(
    factories: Sequence[Callable[[], Probe]],
    *,
    timeout: float = 0.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    announce: Callable[[str], None] | None = None,
) -> Report:
    """Run every probe, re-running only the ones that have not passed yet.

    Why not `docker compose up --wait`: this stack has a one-shot init container
    (``silo-init`` creates the buckets and exits 0) and compose reports any exited
    container as a failure, so ``--wait`` failed a launch that was perfectly healthy.
    Readiness has to be decided by the checks themselves — and retrying only the
    failing probes keeps a 5-minute clamd signature load from being re-probed through
    an already-green store.
    """
    pending: list[Callable[[], Probe]] = list(factories)
    passed: list[Probe] = []
    started = clock()
    while True:
        results = [(factory, factory()) for factory in pending]
        passed.extend(probe for _, probe in results if probe.ok)
        failed = [(factory, probe) for factory, probe in results if not probe.ok]
        if not failed:
            return Report(passed)
        elapsed = clock() - started
        if elapsed >= timeout:
            return Report(passed + [probe for _, probe in failed])
        if announce is not None:
            names = ", ".join(probe.name for _, probe in failed)
            announce(f"  waiting for {names} ({elapsed:.0f}s of {timeout:.0f}s)")
        sleep(min(_RETRY_DELAY_SECONDS, timeout - elapsed))
        pending = [factory for factory, _ in failed]


def _checks(
    *,
    env_file: Path,
    image: str,
    public_raw: str,
    clamav_host: str,
    clamav_port: int,
    api_url: str,
    preflight: bool,
    skip_s3: bool,
    skip_clamav: bool,
    skip_api: bool,
) -> list[Callable[[], Probe]]:
    """The probes this invocation asks for, as callables so ``run_until_ready`` can retry.

    The store probe defaults to the *browser-facing* address, because that is the one a
    human can reach from the machine running this script; the container always gets the
    service name (``minio:9000``) from compose.
    """
    checks: list[Callable[[], Probe]] = []
    if preflight:
        checks.append(lambda: preflight_image(image))
    if not skip_s3:
        checks.append(lambda: check_s3(public_raw))
        # The bucket bootstrap belongs to the store half of the stack: `--skip-s3` marks
        # a run that never recreates the init container (`make rebuild-app`), so checking
        # it there would report a stale verdict about a container nobody touched.
        checks.append(lambda: check_silo_bootstrap(env_file))
    if not skip_clamav:
        checks.append(lambda: check_clamav(clamav_host, clamav_port))
    if not skip_api:
        checks.append(lambda: check_api(api_url))
    return checks


@dataclass(frozen=True)
class FullLaunch:
    """What a full-stack ``up`` runs *and* the backends the API is switched onto."""

    profiles: tuple[str, ...]
    compose_files: tuple[str, ...]
    blob_backend: str
    scanner_backend: str
    s3_skip_reason: str = ""

    def compose_args(self) -> list[str]:
        """Render ``--profile``/``-f`` flags in the order the command line needs them."""
        args: list[str] = []
        for profile in self.profiles:
            args += ["--profile", profile]
        for compose_file in self.compose_files:
            args += ["-f", compose_file]
        return args


def _health_url(endpoint: str) -> str:
    """Turn a configured endpoint into a browsable liveness URL.

    Scheme defaults to ``http``. This is not a re-implementation of the adapter's
    ``ATTACHMENTS_MINIO_PUBLIC_ENDPOINT`` parsing: the probe only needs a URL to GET,
    it does not validate the value (the adapter and config do that, fail-closed).
    """
    base = endpoint if "://" in endpoint else f"http://{endpoint}"
    return f"{base.rstrip('/')}/minio/health/live"


def _http_ok(url: str, *, timeout: float = 5.0) -> tuple[bool, str]:
    """GET a URL and report whether it answered 2xx; never raises for a refused socket."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
            return 200 <= int(response.status) < 300, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except Exception as exc:
        return False, type(exc).__name__


def check_s3(endpoint: str) -> Probe:
    """Probe the store's liveness endpoint — the same address the API's boot check needs."""
    url = _health_url(endpoint)
    ok, detail = _http_ok(url)
    hint = ""
    if not ok:
        hint = (
            f"start the store with `make attach-s3-up`, or point ATTACHMENTS_MINIO_ENDPOINT "
            f"at a reachable endpoint (currently {endpoint!r}); from inside the api container a "
            f"host-side store needs host.docker.internal, an in-network one needs its service name"
        )
    return Probe(name="s3", ok=ok, detail=f"{url} -> {detail}", hint=hint)


def _compose_records(output: str) -> list[dict[str, object]]:
    """Parse ``compose ps --format json`` into records.

    Compose emits one object per line (some releases wrap them in a single array), so
    both shapes are accepted — binding to one would tie the probe to a CLI minor version.
    """
    text = output.strip()
    if not text:
        return []
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        records: list[dict[str, object]] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return [payload] if isinstance(payload, dict) else []


def _is_one_off(record: dict[str, object]) -> bool:
    """True for containers created by ``compose run`` rather than by ``up``.

    ``ps -a`` lists them alongside the managed container — verified against compose
    5.5.1 — so without this filter a manual ``docker compose run silo-init`` that exited
    non-zero would be read as the state of the launch and fail a healthy stack.
    """
    labels = record.get("Labels")
    if not isinstance(labels, str):
        return False
    return any(part.strip() == "com.docker.compose.oneoff=True" for part in labels.split(","))


def _compose_service_state(env_file: Path, service: str) -> tuple[bool, dict[str, object] | None]:
    """Return ``(compose_answered, record)`` for the service's managed container.

    ``compose_answered`` is False when docker/compose could not be consulted at all, so a
    probe never reports a healthy stack as broken because its own tooling is missing —
    the same contract as ``_compose_store_image``. No profile flags: ``ps -a`` lists what
    exists in the project, and naming profiles here would additionally make the result
    depend on the env file satisfying every ``:?`` secret in docker-compose.yml.
    """
    if shutil.which("docker") is None:
        return False, None
    command = ["docker", "compose"]
    if env_file.is_file():
        command += ["--env-file", str(env_file)]
    command += ["ps", "-a", "--format", "json", service]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        return False, None
    managed = [record for record in _compose_records(result.stdout) if not _is_one_off(record)]
    return True, (managed[0] if managed else None)


def _as_int(value: object) -> int | None:
    """Read an exit code that compose may serialise as a number or a string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return None


def check_silo_bootstrap(env_file: Path) -> Probe:
    """Verify the one-shot bucket bootstrap finished with exit code 0.

    ``silo-init`` is an init container: it creates the buckets and exits, so compose and
    the Docker UI show it as *not running*. That is its correct end state and must not be
    read as a failure — the same fact that forced readiness onto this probe instead of
    ``docker compose up --wait``. What is a failure is a non-zero exit, and it is an
    invisible one: the API creates its own bucket at boot, so a stack with a broken
    bootstrap looks perfectly healthy while Langfuse v3, which requires the ``langfuse``
    bucket, ingests into nothing and tracing stays silently empty (020).
    """
    name = _SILO_INIT_SERVICE
    queried, record = _compose_service_state(env_file, name)
    if not queried:
        return Probe(name=name, ok=True, detail="not checked: docker compose unavailable")
    if record is None:
        # A launch without the S3/observability profile legitimately has no init
        # container, and its store probe fails on its own. Reporting that here as a
        # failure would also make `--wait` spin on a service that will never appear.
        return Probe(name=name, ok=True, detail="not created: S3/observability profile not in this launch")
    state = str(record.get("State", "")).strip().lower()
    status = str(record.get("Status", "")).strip() or state
    container = str(record.get("Name") or record.get("Names") or name)
    if state != "exited":
        # Still running or restarting: not finished yet, which `--wait` may retry.
        return Probe(name=name, ok=False, detail=f"{container} -> {status} (bootstrap not finished)")
    exit_code = _as_int(record.get("ExitCode"))
    if exit_code == 0:
        return Probe(name=name, ok=True, detail=f"{container} exited 0 -> buckets ready")
    return Probe(
        name=name,
        ok=False,
        detail=f"{container} -> {status} (exit {exit_code if exit_code is not None else 'unknown'})",
        hint=(
            "the bucket bootstrap failed, so the `langfuse` bucket may be missing: Langfuse v3 "
            "ingests through S3 and would stay silently empty rather than error. Read "
            "`docker compose logs silo-init`, then re-run it with "
            "`docker compose --profile attachments-s3 up silo-init`"
        ),
    )


def check_clamav(host: str, port: int, *, timeout: float = 5.0) -> Probe:
    """Send the documented ``zPING`` command and require ``PONG`` back.

    A TCP connect alone is not enough: clamd accepts the socket before its signature
    database is loaded, and the app would still fail closed with ``scan_failed``.
    """
    name = "clamav"
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"zPING\0")
            answer = sock.recv(64)
    except OSError as exc:
        return Probe(
            name=name,
            ok=False,
            detail=f"{host}:{port} -> {type(exc).__name__}",
            hint=(
                "start it with `make attach-up` (profile attachments); a cold start pulls "
                "signatures and can take minutes — a dead engine makes every upload "
                "quarantined with rejection_reason=scan_failed"
            ),
        )
    ok = b"PONG" in answer.upper()
    return Probe(name=name, ok=ok, detail=f"{host}:{port} -> {answer!r}")


def check_api(base_url: str) -> Probe:
    """Probe the API health endpoint, so an attachment failure is not guessed at."""
    url = f"{base_url.rstrip('/')}/health"
    ok, detail = _http_ok(url)
    hint = "" if ok else "start the API stack (`make up` / menu: Start stack) before probing"
    return Probe(name="api", ok=ok, detail=f"{url} -> {detail}", hint=hint)


def resolve_store_image(env_file: Path) -> str:
    """Return the image the ``minio`` service will actually run.

    Read from compose instead of from a copy kept in this file. The store moved from
    MinIO to the Pigsty Silo fork, and a duplicated default stayed behind validating the
    *dead* MinIO image while compose ran Silo — a green preflight for the wrong
    container, which is the exact class of drift this module exists to prevent (010).

    The image is deliberately not an env knob any more (``ATTACHMENTS_MINIO_IMAGE``):
    an env file must not be able to beat the tag+digest pin in docker-compose.yml (050).
    """
    return _compose_store_image(env_file) or _FALLBACK_STORE_IMAGE


def _compose_store_image(env_file: Path) -> str | None:
    """Resolve ``services.minio.image`` through compose, or ``None`` when impossible."""
    if shutil.which("docker") is None:
        return None
    command = ["docker", "compose"]
    if env_file.is_file():
        command += ["--env-file", str(env_file)]
    # The profile is required for compose to include the service in `config` output at all.
    command += ["--profile", "attachments-s3", "config", "--format", "json"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    services = payload.get("services")
    if not isinstance(services, dict):
        return None
    service = services.get("minio")
    if not isinstance(service, dict):
        return None
    image = service.get("image")
    return image if isinstance(image, str) and image else None


def preflight_image(image: str) -> Probe:
    """Confirm the configured S3 image is actually pullable before `up` fails obscurely."""
    name = "minio_image"
    if shutil.which("docker") is None:
        return Probe(name=name, ok=False, detail="docker not found on PATH", hint="install Docker")
    result = subprocess.run(  # noqa: S603
        ["docker", "manifest", "inspect", image],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return Probe(name=name, ok=True, detail=f"{image} -> manifest available")
    output = (result.stderr or result.stdout).strip().splitlines()
    reason = output[0] if output else f"exit {result.returncode}"
    return Probe(
        name=name,
        ok=False,
        detail=f"{image} -> {reason}",
        hint=(
            "The store image is pinned by tag+digest in docker-compose.yml (Silo — the "
            "maintained MinIO fork; upstream MinIO archived its community edition and "
            "deleted its Docker Hub images on 2026-09-11). A failure here is registry "
            "access, not a compose bug: point the `minio` service at a mirror you can "
            "reach, or keep ATTACHMENTS_BLOB_BACKEND=filesystem locally and skip the store"
        ),
    )


def full_launch(image: str) -> FullLaunch:
    """Decide the flags for a full-stack ``up`` — profiles *and* backend overlays.

    A profile only decides which containers exist; the API reads its backends from
    ``ATTACHMENTS_BLOB_BACKEND`` / ``ATTACHMENTS_SCANNER_BACKEND``. So a full launch has
    to do both halves, or the AV/S3 containers just sit idle (runbook §16.8). The two
    overlays are split by component on purpose: an unreachable object store must not also
    switch the scanner back off, and neither overlay is loaded by a plain ``make up``.

    The only fact that can fail is the S3 image being pullable, and it decides the
    ``attachments-s3`` profile and its overlay together — the API can never be pointed at
    a store that was not started. Both entry points (Makefile, menu) expand this same
    rule so they cannot drift (010), which is why it lives here and not in a shell.
    """
    profiles = ["docker-mcp", "docker-api", "attachments"]
    compose_files = [_BASE_COMPOSE_FILE, _PROFILE_COMPOSE_FILE, _AV_COMPOSE_FILE]
    probe = preflight_image(image)
    if probe.ok:
        profiles.append("attachments-s3")
        compose_files.append(_S3_COMPOSE_FILE)
        return FullLaunch(tuple(profiles), tuple(compose_files), "minio", "clamav")
    return FullLaunch(
        tuple(profiles),
        tuple(compose_files),
        "filesystem",
        "clamav",
        s3_skip_reason=probe.hint or probe.detail,
    )


def mode_report(env: dict[str, str], *, blob: str, scanner: str, extra: list[str] | None = None) -> list[str]:
    """Describe the backends the API will actually use — not the containers that run.

    Starting the ``attachments``/``attachments-s3`` profiles does not switch the API onto
    them: that is a separate pair of knobs (``ATTACHMENTS_BLOB_BACKEND`` /
    ``ATTACHMENTS_SCANNER_BACKEND``), plus the capability knob
    ``ATTACHMENTS_IMAGE_OCR_BACKEND`` that decides whether images are accepted at all.
    All of them are reported from one implementation so
    the Makefile and ``scripts/menu.ps1`` cannot drift (010), and an idle container is
    impossible to mistake for a live code path.

    The caller passes the backends because "plain `up`" reads them from the env file while
    "full launch" derives them from the overlays it is about to load; the defaults mirror
    ``core/config/attachments.py`` (``memory`` / ``disabled``), and the wiring layer
    refuses ``memory``/``filesystem`` outside local/test (020).
    """
    lines = [f"blob_backend={blob}", f"scanner_backend={scanner}"]

    if blob == "minio":
        # Fail-closed at startup, not on the first upload: the API refuses to boot with
        # an empty credential, so warn before the operator restarts into a crash loop.
        if not env.get("ATTACHMENTS_MINIO_ACCESS_KEY") or not env.get("ATTACHMENTS_MINIO_SECRET_KEY"):
            lines.append("warn: blob_backend=minio with empty ATTACHMENTS_MINIO_ACCESS_KEY/SECRET_KEY")
            lines.append("warn: the api refuses to start until both are set (fail-closed)")
    else:
        lines.append('idle: minio container is unused — set ATTACHMENTS_BLOB_BACKEND="minio" to use it')

    if scanner == "clamav":
        if not env.get("ATTACHMENTS_CLAMAV_HOST", "").strip():
            lines.append("warn: scanner_backend=clamav with empty ATTACHMENTS_CLAMAV_HOST")
            lines.append("warn: the api refuses to start until it is set (fail-closed)")
    else:
        lines.append('idle: clamav container is unused — set ATTACHMENTS_SCANNER_BACKEND="clamav" to use it')

    lines.extend(_image_ocr_lines(env))

    if extra:
        lines.extend(extra)
    return lines


def _image_ocr_lines(env: dict[str, str]) -> list[str]:
    """Report the image-OCR axis, because images have no text layer to fall back on.

    A wrong ``blob``/``scanner`` value shows up as a broken upload; a missing OCR backend
    shows up as ``reason="mime_not_allowed"`` at ``init`` — i.e. "image files are simply
    not accepted" (055: intake is capability-gated). That reads like a client bug, so the
    axis is printed alongside the other two, with the same fail-closed warning style.
    """
    backend = env.get("ATTACHMENTS_IMAGE_OCR_BACKEND") or _SETTINGS_DEFAULT_IMAGE_OCR_BACKEND
    model = env.get("ATTACHMENTS_IMAGE_OCR_MODEL", "")

    if backend == "disabled":
        return [
            "image_ocr_backend=disabled",
            'idle: image/* is refused at intake — set ATTACHMENTS_IMAGE_OCR_BACKEND="auto" (or gateway)',
        ]

    if backend == "tesseract":
        return ["image_ocr_backend=tesseract", "note: Vision escalate disabled (local OCR only)"]

    if backend == "auto":
        lines = [f"image_ocr_backend=auto model={model or '<none — tesseract-only if installed>'}"]
        if not model.strip():
            lines.append("note: ATTACHMENTS_IMAGE_OCR_MODEL empty — Vision escalate unavailable")
        return lines

    lines = [f"image_ocr_backend=gateway model={model or '<empty>'}"]
    if not model.strip():
        lines.append("warn: image_ocr_backend=gateway with empty ATTACHMENTS_IMAGE_OCR_MODEL")
        lines.append("warn: the api refuses to start until it is set (fail-closed)")
    return lines


def main() -> int:
    """Run the requested probes and print a machine-readable report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=_DEFAULT_ENV_FILE, help=f"default: {_DEFAULT_ENV_FILE}")
    parser.add_argument("--preflight-image", action="store_true", help="check the S3 image is pullable")
    parser.add_argument("--full", action="store_true", help="with --mode: report the full-launch backends")
    parser.add_argument("--mode", action="store_true", help="print the backends the API will use, then exit")
    parser.add_argument(
        "--compose-args",
        action="store_true",
        help="print the --profile/-f flags for a full-stack up (S3 only if its image is pullable), then exit",
    )
    parser.add_argument("--skip-s3", action="store_true", help="skip the object-store liveness probe")
    parser.add_argument("--skip-clamav", action="store_true", help="skip the AV engine probe")
    parser.add_argument("--skip-api", action="store_true", help="skip the API health probe")
    parser.add_argument(
        "--wait",
        type=float,
        default=0.0,
        metavar="SECONDS",
        help="re-check probes that are not ready yet, for up to SECONDS (0 = a single pass)",
    )
    parser.add_argument("--json", action="store_true", help="also dump the report as JSON")
    args = parser.parse_args()

    env = _read_env_file(Path(args.env_file))
    image = resolve_store_image(Path(args.env_file))
    if env.get("ATTACHMENTS_MINIO_IMAGE"):
        # Silently dropping an operator's setting would be worse than the drift it causes.
        print(
            "warn: ATTACHMENTS_MINIO_IMAGE is set but ignored — the store image is pinned "
            "by tag+digest in docker-compose.yml; change it there (050)",
            file=sys.stderr,
        )

    if args.mode:
        # Purely informational: no network beyond the S3 preflight (only for --full), no
        # container, non-fatal exit code — it answers "will the API actually use the
        # containers I just started?".
        if args.full:
            plan = full_launch(image)
            extra = [f"note: S3 profile+overlay skipped — {plan.s3_skip_reason}"] if plan.s3_skip_reason else []
            lines = mode_report(env, blob=plan.blob_backend, scanner=plan.scanner_backend, extra=extra)
        else:
            lines = mode_report(
                env,
                blob=env.get("ATTACHMENTS_BLOB_BACKEND") or _SETTINGS_DEFAULT_BLOB_BACKEND,
                scanner=env.get("ATTACHMENTS_SCANNER_BACKEND") or _SETTINGS_DEFAULT_SCANNER_BACKEND,
            )
        for line in lines:
            print(line)
        return 0

    if args.compose_args:
        # stdout is captured by `$(shell ...)` in the Makefile and by the menu, so the
        # flags stay alone on stdout while the human-readable reason for skipping S3
        # goes to stderr.
        plan = full_launch(image)
        if plan.s3_skip_reason:
            print(f"S3 profile skipped: {plan.s3_skip_reason}", file=sys.stderr)
        print(" ".join(plan.compose_args()))
        return 0

    report = run_until_ready(
        _checks(
            env_file=Path(args.env_file),
            image=image,
            public_raw=env.get("ATTACHMENTS_MINIO_PUBLIC_ENDPOINT")
            or env.get("ATTACHMENTS_MINIO_ENDPOINT", _DEFAULT_MINIO_ENDPOINT),
            clamav_host=env.get("ATTACHMENTS_CLAMAV_HOST", _DEFAULT_CLAMAV_HOST),
            clamav_port=int(env.get("ATTACHMENTS_CLAMAV_PORT", _DEFAULT_CLAMAV_PORT)),
            api_url=env.get("ATTACHMENTS_PROBE_API_URL", _DEFAULT_API_URL),
            preflight=args.preflight_image,
            skip_s3=args.skip_s3,
            skip_clamav=args.skip_clamav,
            skip_api=args.skip_api,
        ),
        timeout=args.wait,
        announce=lambda message: print(message, file=sys.stderr),
    )

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    for probe in report.probes:
        marker = "OK  " if probe.ok else "FAIL"
        print(f"{marker} {probe.name}: {probe.detail}")
        if probe.hint:
            print(f"     hint: {probe.hint}")

    if report.failed:
        print("attachments_probe: FAILED")
        return 1
    print("attachments_probe: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
