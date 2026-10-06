"""Attachments stack probe: object store, AV engine, API, and S3 image preflight.

Usage:
  poetry run python scripts/attachments_probe.py                # all reachable checks
  poetry run python scripts/attachments_probe.py --preflight-image
  poetry run python scripts/attachments_probe.py --s3 --clamav

Why this exists: the attachment pipeline is fail-closed, so a wrong address shows up
as ``quarantined``/``scan_failed`` rows rather than an error at boot. This script
turns "uploads do not work" into the one component that is actually down, and it
gives the Makefile and ``scripts/menu.ps1`` a single implementation to call instead
of two drifting copies of the same checks (010).

``--preflight-image`` is separate from a plain ``docker compose up`` on purpose:
the upstream MinIO images are not anonymously pullable (Docker Hub 404, quay.io 401,
ghcr.io 403), so the default failure is a registry authorization error that reads
like a broken compose file. The preflight names the real cause.
"""

from __future__ import annotations

import argparse
import json
import shutil
import socket
import subprocess
import urllib.error
import urllib.request

from dataclasses import dataclass, field
from pathlib import Path

_DEFAULT_ENV_FILE = "env/.env"
_DEFAULT_IMAGE = "quay.io/minio/minio:RELEASE.2025-04-22T22-12-26Z"
_DEFAULT_MINIO_ENDPOINT = "localhost:9000"
_DEFAULT_CLAMAV_HOST = "localhost"
_DEFAULT_CLAMAV_PORT = 3310
_DEFAULT_API_URL = "http://127.0.0.1:8000"


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

    def add(self, probe: Probe) -> None:
        self.probes.append(probe)

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
            "MinIO publishes no anonymously pullable image (Docker Hub 404 / quay.io 401 / "
            "ghcr.io 403), so this is a registry-access problem, not a compose bug: point "
            "ATTACHMENTS_MINIO_IMAGE at an internal mirror, or keep ATTACHMENTS_BLOB_BACKEND="
            "filesystem locally and skip the store entirely"
        ),
    )


def main() -> int:
    """Run the requested probes and print a machine-readable report."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--env-file", default=_DEFAULT_ENV_FILE, help=f"default: {_DEFAULT_ENV_FILE}")
    parser.add_argument("--preflight-image", action="store_true", help="check the S3 image is pullable")
    parser.add_argument("--skip-s3", action="store_true", help="skip the object-store liveness probe")
    parser.add_argument("--skip-clamav", action="store_true", help="skip the AV engine probe")
    parser.add_argument("--skip-api", action="store_true", help="skip the API health probe")
    parser.add_argument("--json", action="store_true", help="also dump the report as JSON")
    args = parser.parse_args()

    env = _read_env_file(Path(args.env_file))
    # The probe defaults to the *browser-facing* address, because that is the one a
    # human can reach from the machine running this script.
    public_raw = env.get("ATTACHMENTS_MINIO_PUBLIC_ENDPOINT") or env.get(
        "ATTACHMENTS_MINIO_ENDPOINT", _DEFAULT_MINIO_ENDPOINT
    )
    clamav_host = env.get("ATTACHMENTS_CLAMAV_HOST", _DEFAULT_CLAMAV_HOST)
    clamav_port = int(env.get("ATTACHMENTS_CLAMAV_PORT", _DEFAULT_CLAMAV_PORT))
    api_url = env.get("ATTACHMENTS_PROBE_API_URL", _DEFAULT_API_URL)
    image = env.get("ATTACHMENTS_MINIO_IMAGE", _DEFAULT_IMAGE)

    report = Report()
    if args.preflight_image:
        report.add(preflight_image(image))
    if not args.skip_s3:
        report.add(check_s3(public_raw))
    if not args.skip_clamav:
        report.add(check_clamav(clamav_host, clamav_port))
    if not args.skip_api:
        report.add(check_api(api_url))

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
