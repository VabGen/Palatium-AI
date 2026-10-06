"""Container hardening is a contract, not prose (020, 050).

Two failures on this 16 GB dev host cost hours precisely because nothing in CI could
see them, and both are re-introduced by *deleting a few lines of YAML*:

* ``clamav/clamav:1.5.4-debian`` starts the daemon detached (``clamd --foreground &``)
  and then execs ``tail -f /dev/null``, so PID 1 is ``tail``. A reaped clamd therefore
  leaves the container ``Up`` — and its TCP healthcheck can even keep passing — while
  every upload blocks until the application's scan timeout. The fix is a PID-1 wrapper
  around ``/init``, and a wrapper is worth nothing unless it is both wired in *and*
  intact, which is why the script is checked at the byte level below.
* With no per-container ceiling a runaway process is reaped by the *VM-wide* OOM
  killer, which picks the largest RSS (clamd, postgres) and cascades into Postgres
  crash-recovery; the API then fails every request with ``socket hang up``.

These tests assert the wiring, not somebody's favourite numbers: a ceiling must
exist, the supervisor must be loaded, and the two must stay connected.
"""

from __future__ import annotations

import re

from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
WATCHDOG_SCRIPT = REPO_ROOT / "deploy" / "clamav" / "clamd-watchdog.sh"

# Path *inside* the container; the compose entrypoint and the volume target must
# agree on it or the wrapper either never runs (silently) or runs a stale file.
WATCHDOG_CONTAINER_PATH = "/usr/local/bin/clamd-watchdog.sh"

# Services that must not be able to eat the whole Docker VM, and whose ceilings a
# plain `docker compose config` can see (no profile needed, so `config -q` in CI and
# a bare checkout agree). Postgres is the one whose death is catastrophic —
# crash-recovery with multi-minute fsync loops — so a missing ceiling here is a
# regression, not a tuning preference.
CEILING_REQUIRED = (
    "postgres",
    "redis",
    "neo4j",
    "litellm",
    "api",
)

# The ClamAV signature database is resident in clamd's RSS (~1 GiB for the bundled
# main+daily+bytecode set), so a ceiling below this makes the daemon OOM itself.
CLAMD_DATABASE_FLOOR_BYTES = 1024 * 1024 * 1024

_MEMORY_UNITS = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3}
_MEMORY_RE = re.compile(r"(\d+)([bkmg]?)b?")

_MIB = 1024 * 1024

# `docker info --format '{{.MemTotal}}'` on the 16 GB host that hit this incident, in
# MiB (Docker Desktop's default VM size). The ceilings are a budget against *this*
# number, because cgroup limits only help if all containers can peak at once without
# the VM-wide killer firing — which is what cascaded into the Postgres crash loop.
DOCKER_VM_TOTAL_MIB = 7884

# Ceilings of the default launch (`make up`: data plane + app + attachments) and of MCP.
# Included in the budget, but their *presence* is only asserted for the profile-independent
# services above.
BUDGETED_SERVICES = (*CEILING_REQUIRED, "minio", "mcp-edms", "mcp-analytics")

# Profile-gated observability (Langfuse v3). Deliberately *not* part of the budget above,
# and the split is asserted below rather than assumed: `make up` must fit the default VM,
# `make up-full` needs a larger one. Quietly folding ClickHouse into the default profile is
# exactly how the VM-wide OOM killer gets invoked — and how Postgres lands in crash-recovery.
OBSERVABILITY_SERVICES = ("clickhouse", "langfuse-web", "langfuse-worker")

# Docker VM size at which core + observability can peak together: 9344 MiB of declared
# ceilings, rounded up to the practical `memory=12GB` in %USERPROFILE%\.wslconfig.
OBSERVABILITY_VM_FLOOR_MIB = 12 * 1024


def _compose() -> dict[str, Any]:
    loaded = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "docker-compose.yml must parse to a mapping"
    return loaded


def _service(name: str) -> dict[str, Any]:
    services: dict[str, Any] = _compose().get("services", {})
    assert name in services, f"service {name!r} missing from docker-compose.yml"
    service = services[name]
    assert isinstance(service, dict), f"service {name!r} must be a mapping"
    return service


def _memory_bytes(value: object) -> int:
    """Compose memory syntax: a plain byte count or ``512m`` / ``1g`` style."""
    if isinstance(value, int):
        return value
    match = _MEMORY_RE.fullmatch(str(value).strip().lower())
    assert match, f"unparsable memory limit: {value!r}"
    return int(match.group(1)) * _MEMORY_UNITS[match.group(2)]


def _ceiling_bytes(service_name: str) -> int:
    """The declared ceiling of ``service_name``; fails loudly when it is missing."""
    service = _service(service_name)
    assert "mem_limit" in service, f"{service_name} has no mem_limit; a runaway there can kill postgres"
    limit = _memory_bytes(service["mem_limit"])
    assert limit > 0, f"{service_name} mem_limit must be positive"
    return limit


def test_watchdog_script_uses_lf_line_endings() -> None:
    """CRLF turns ``set -euo pipefail`` into ``set: pipefail: invalid option name``.

    ``.gitattributes`` forces ``eol=lf`` for ``*.sh``, but an editor saving CRLF on
    Windows (as happened while writing this script) breaks the bind-mounted file in a
    way that only shows up as a crash-looping container at ``up`` time. Checked on raw
    bytes on purpose: ``read_text()`` would translate the endings away.
    """
    raw = WATCHDOG_SCRIPT.read_bytes()
    assert raw.startswith(b"#!/usr/bin/env bash\n"), "shebang must be the first line, LF-terminated"
    assert b"\r" not in raw, "clamd-watchdog.sh must be stored with LF endings (see .gitattributes)"


def test_watchdog_supervises_init_without_policing_cold_start() -> None:
    """The wrapper must own /init, forward stop signals, and tolerate slow startup."""
    text = WATCHDOG_SCRIPT.read_text(encoding="utf-8")

    assert "/init &" in text, "the upstream entrypoint must run in the background so its exit is observable"
    assert "wait " in text, "the wrapper must propagate /init's exit status instead of exiting 0 unconditionally"
    assert "TERM" in text, "`docker stop` must stay a clean shutdown (signal forwarding)"
    # Liveness is the same contract the app uses, so a wedged daemon is caught too.
    assert "/dev/tcp/127.0.0.1/" in text, "liveness must be probed over clamd's TCP socket"
    # A cold container spends minutes in freshclam before clamd exists; failing then
    # would turn a slow first start into a restart loop.
    assert "clamd_seen" in text, "the wrapper must only react once clamd has answered at least once"


def test_compose_runs_the_watchdog_as_clamav_entrypoint() -> None:
    """Wiring: the script must be executed *and* mounted at the path it is executed from."""
    clamav = _service("clamav")
    entrypoint = [str(part) for part in clamav.get("entrypoint", [])]

    assert entrypoint[:1] == ["/bin/bash"], f"clamav entrypoint must run the wrapper, got {entrypoint}"
    assert WATCHDOG_CONTAINER_PATH in entrypoint, f"entrypoint does not reference {WATCHDOG_CONTAINER_PATH}"

    mounted = [str(volume) for volume in clamav.get("volumes", []) if "clamd-watchdog.sh" in str(volume)]
    assert mounted, "the watchdog script is not mounted into the container"
    source, target, *options = mounted[0].split(":")
    assert (REPO_ROOT / source).resolve() == WATCHDOG_SCRIPT.resolve(), f"unexpected mount source: {source}"
    assert target == WATCHDOG_CONTAINER_PATH, f"mount target {target!r} != entrypoint path"
    assert "ro" in options, "the mounted script must be read-only (020)"


def test_clamav_restart_policy_can_act_on_the_watchdog_exit() -> None:
    """A wrapper that exits 1 is only useful if Docker then recreates the container."""
    policy = str(_service("clamav").get("restart", ""))
    assert policy in {"unless-stopped", "always", "on-failure"}, f"restart policy {policy!r} cannot recover clamd"


def test_clamav_ceiling_clears_the_signature_database() -> None:
    """Below the resident database size the daemon OOMs in a loop, not once."""
    limit = _ceiling_bytes("clamav")
    assert limit >= CLAMD_DATABASE_FLOOR_BYTES, f"clamav mem_limit {limit} is under the signature database footprint"


@pytest.mark.parametrize("service_name", CEILING_REQUIRED)
def test_stateful_service_declares_a_memory_ceiling(service_name: str) -> None:
    """No ceiling means the VM-wide OOM killer chooses the victim — usually postgres."""
    assert _ceiling_bytes(service_name) > 0


def test_memory_ceilings_fit_inside_the_docker_vm() -> None:
    """The ceilings are one budget: all of them may peak at the same time.

    Per-container limits only protect Postgres if the *sum* fits the VM. Otherwise the
    VM-wide killer still fires and the failure mode is unchanged — so raising a ceiling
    means lowering another or giving Docker Desktop more RAM, not just editing a number.
    """
    occupied = sum(_ceiling_bytes(name) for name in BUDGETED_SERVICES)
    occupied_mib = occupied // _MIB
    assert occupied_mib <= DOCKER_VM_TOTAL_MIB, (
        f"memory ceilings total {occupied_mib} MiB, over the {DOCKER_VM_TOTAL_MIB} MiB Docker VM: "
        f"{', '.join(f'{name}={_ceiling_bytes(name) // _MIB}m' for name in BUDGETED_SERVICES)}"
    )


@pytest.mark.parametrize("service_name", OBSERVABILITY_SERVICES)
def test_observability_service_declares_a_memory_ceiling(service_name: str) -> None:
    """Same contract as the core services: an unbounded ClickHouse is a VM-wide risk."""
    assert _ceiling_bytes(service_name) > 0


def test_observability_is_profile_gated_because_it_cannot_fit_the_default_vm() -> None:
    """`make up-full` adds ~3328 MiB on top of a ~6016 MiB core — past the 7884 MiB VM.

    Three things must stay true, and none of them is visible from the YAML alone: the
    default launch fits the default VM (so the profile gate is a memory decision, not
    cosmetics), the combined stacks do *not* fit it (the gate is still required), and the
    documented larger-VM floor covers both at once. Raising a ceiling therefore means
    raising the floor or lowering another number — not editing this test.
    """
    core_mib = sum(_ceiling_bytes(name) for name in BUDGETED_SERVICES) // _MIB
    observability_mib = sum(_ceiling_bytes(name) for name in OBSERVABILITY_SERVICES) // _MIB
    combined_mib = core_mib + observability_mib

    assert core_mib <= DOCKER_VM_TOTAL_MIB, f"default launch {core_mib} MiB exceeds the default VM"
    assert combined_mib > DOCKER_VM_TOTAL_MIB, (
        f"observability now fits the default VM ({combined_mib} <= {DOCKER_VM_TOTAL_MIB} MiB) — "
        "reconsider the profile gate in docker-compose.yml"
    )
    assert combined_mib <= OBSERVABILITY_VM_FLOOR_MIB, (
        f"core {core_mib} + observability {observability_mib} = {combined_mib} MiB exceeds the "
        f"documented {OBSERVABILITY_VM_FLOOR_MIB} MiB floor: raise the floor or lower a ceiling"
    )


def test_litellm_healthcheck_covers_its_migration_startup() -> None:
    """A cold LiteLLM runs ``prisma migrate deploy`` before port 4000 opens.

    With a grace period shorter than that run, the API's ``condition: service_healthy``
    dependency aborts a plain ``up`` with "container litellm is unhealthy" — a recreate
    would then need a second attempt to succeed.
    """
    healthcheck = _service("litellm").get("healthcheck", {})
    start_period = str(healthcheck.get("start_period", ""))
    assert start_period.endswith("s"), f"litellm start_period must be explicit, got {start_period!r}"
    assert int(start_period.removesuffix("s")) >= 120, (
        f"litellm start_period {start_period} is shorter than the migration run"
    )


def test_litellm_runs_a_single_worker() -> None:
    """Each LiteLLM worker forks its own Prisma (Rust) query engine.

    That fork storm — not the LLM traffic — is what exhausted the VM and got Postgres
    killed. Scaling workers again requires more host RAM first.
    """
    command = [str(part) for part in _service("litellm").get("command", [])]
    assert "--num_workers" in command, "litellm must pin its worker count explicitly"
    assert command[command.index("--num_workers") + 1] == "1", f"unexpected worker count in {command}"


def test_postgres_has_shared_memory_beyond_the_docker_default() -> None:
    """``/dev/shm`` is 64 MiB by default; Postgres needs it for parallel query workers.

    ``dynamic_shared_memory_type=posix`` (the image's default) means parallel workers and
    ``parallel_hash_join`` allocate their segments in ``/dev/shm``. Past that ceiling the
    *query* dies with "could not resize shared memory segment ... No space left on device",
    which is invisible until several analytic scans run at once — a single-user dev stack
    never reproduces it, so the number is asserted here rather than discovered in staging.
    """
    shm = _service("postgres").get("shm_size")
    assert shm is not None, "postgres needs an explicit shm_size; the 64 MiB default is a latent query failure"
    assert _memory_bytes(shm) >= 256 * _MIB, f"postgres shm_size {shm!r} is too tight for parallel workers"


def test_api_reaches_postgres_by_compose_service_name() -> None:
    """The API must dial the ``postgres`` service, never ``localhost``.

    ``env_file: env/.env`` is authored for the Poetry host profile, where the DB runs on
    the host and ``POSTGRES_HOST=localhost``. Routing that value back into the container
    with ``environment: POSTGRES_HOST: ${POSTGRES_HOST:-...}`` made the API dial *itself*:
    every start died in a crash loop with ``[Errno 111] Connect call failed ('::1', 5432)``
    while Postgres was perfectly healthy, so the API never reached ``healthy`` and the
    default ``:-`` branch was dead code — ``--env-file`` always defines the variable.
    The literal is deliberate for the same reason ``REDIS_HOST: redis`` is: inside the
    compose network only the service name resolves (020).
    """
    host = _service("api")["environment"]["POSTGRES_HOST"]

    assert "{" not in str(host), f"POSTGRES_HOST must not interpolate the host profile: {host!r}"
    assert str(host) == "postgres", f"the API must reach the DB as 'postgres', got {host!r}"


def test_postgres_image_pin_and_volume_target_agree_on_the_major() -> None:
    """A major bump relocates PGDATA, and a stale mount target loses the cluster silently.

    ``postgres:18`` sets ``PGDATA=/var/lib/postgresql/18/docker`` and declares its VOLUME
    as the *parent* ``/var/lib/postgresql``, where pre-18 images used
    ``/var/lib/postgresql/data``. Mounting the old path does not fail loudly: the server
    initialises into an *anonymous* volume, the named volume stays empty, and ``down -v``
    never removes the real data — a silent data-location change, not a crash. The pin and
    the mount are therefore two halves of one contract and are asserted together.
    """
    service = _service("postgres")
    image = str(service["image"])

    assert "@sha256:" in image, f"postgres image must be pinned by digest (025): {image!r}"
    tag = image.split("@", 1)[0].rsplit(":", 1)[1]
    major = int(tag.removeprefix("pg"))

    mounts = [str(volume) for volume in service.get("volumes", []) if "pgdata" in str(volume)]
    assert mounts, "the postgres data volume is not mounted"
    target = mounts[0].split(":")[1]

    expected = "/var/lib/postgresql" if major >= 18 else "/var/lib/postgresql/data"
    assert target == expected, (
        f"image {tag} keeps PGDATA under {expected}, but the volume is mounted at {target}: "
        "the cluster would land in an anonymous volume and the named one would stay empty"
    )
