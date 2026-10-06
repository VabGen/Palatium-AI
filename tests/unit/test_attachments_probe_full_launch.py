"""Full-launch planning for the attachments stack (`make up`, §16.8/§16.9).

A compose profile decides which containers *exist*; the API decides what it talks to
from ``ATTACHMENTS_BLOB_BACKEND`` / ``ATTACHMENTS_SCANNER_BACKEND``. These tests pin the
rule that a full launch must move both together — otherwise the AV/S3 containers come up
idle, which is a "full launch" that silently is not one.
"""

from __future__ import annotations

import importlib.util
import sys

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROBE_PATH = _REPO_ROOT / "scripts" / "attachments_probe.py"


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("attachments_probe", _PROBE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["attachments_probe"] = module
    spec.loader.exec_module(module)
    return module


def _stub_preflight(mod, *, ok: bool, hint: str = ""):
    return lambda image: mod.Probe(name="minio_image", ok=ok, detail=f"{image} -> stub", hint=hint)


def test_full_launch_switches_api_onto_the_containers_it_starts(monkeypatch) -> None:
    mod = _load_probe_module()
    monkeypatch.setattr(mod, "preflight_image", _stub_preflight(mod, ok=True))

    plan = mod.full_launch("registry.example/minio:1")

    assert plan.blob_backend == "minio"
    assert plan.scanner_backend == "clamav"
    assert plan.s3_skip_reason == ""
    assert "attachments" in plan.profiles
    assert "attachments-s3" in plan.profiles
    assert "docker-compose.attachments-av.yml" in plan.compose_files
    assert "docker-compose.attachments-s3.yml" in plan.compose_files


def test_full_launch_keeps_av_and_degrades_the_store_when_image_is_blocked(monkeypatch) -> None:
    mod = _load_probe_module()
    monkeypatch.setattr(mod, "preflight_image", _stub_preflight(mod, ok=False, hint="mirror it"))

    plan = mod.full_launch("denied/image")

    # The API must never point at a container that was not started...
    assert plan.blob_backend == "filesystem"
    assert "attachments-s3" not in plan.profiles
    assert "docker-compose.attachments-s3.yml" not in plan.compose_files
    # ...while an unreachable store must not also switch the scanner back off.
    assert plan.scanner_backend == "clamav"
    assert "docker-compose.attachments-av.yml" in plan.compose_files
    assert plan.s3_skip_reason == "mirror it"


def test_compose_args_keep_base_and_profile_overrides_explicit(monkeypatch) -> None:
    mod = _load_probe_module()
    monkeypatch.setattr(mod, "preflight_image", _stub_preflight(mod, ok=True))

    args = mod.full_launch("img").compose_args()

    profiles = [args[i + 1] for i, arg in enumerate(args) if arg == "--profile"]
    files = [args[i + 1] for i, arg in enumerate(args) if arg == "-f"]
    assert profiles == ["docker-mcp", "docker-api", "attachments", "attachments-s3"]
    # Passing any `-f` disables compose's auto-load of docker-compose.override.yml, which
    # carries the dev profile split — dropping it would silently change which services exist.
    assert files == [
        "docker-compose.yml",
        "docker-compose.override.yml",
        "docker-compose.attachments-av.yml",
        "docker-compose.attachments-s3.yml",
    ]


def test_mode_report_marks_started_but_unused_containers_idle() -> None:
    mod = _load_probe_module()

    lines = mod.mode_report({}, blob="filesystem", scanner="disabled")

    assert lines[0] == "blob_backend=filesystem"
    assert lines[1] == "scanner_backend=disabled"
    assert any(line.startswith("idle: minio") for line in lines)
    assert any(line.startswith("idle: clamav") for line in lines)
    # Images are the third axis: default auto still prints the OCR axis so operators
    # see whether Vision escalate is wired (055: capability-gated intake).
    assert any(line.startswith("image_ocr_backend=auto") for line in lines)
    assert any("tesseract-only" in line or "Vision escalate" in line for line in lines)


def test_mode_report_warns_fail_closed_when_the_full_launch_is_unconfigured() -> None:
    mod = _load_probe_module()
    # OCR is switched on but unwired, so all three knobs must warn rather than
    # silently degrade (020: fail-closed).
    env = {"ATTACHMENTS_IMAGE_OCR_BACKEND": "gateway"}

    lines = mod.mode_report(env, blob="minio", scanner="clamav")

    # Every line past the two mode lines is a warning — the one exception is the OCR
    # line naming the alias it failed to find.
    assert all(line.startswith("warn:") for line in lines[2:] if not line.startswith("image_ocr_backend="))
    assert not any(line.startswith("idle:") for line in lines)
    assert any("ATTACHMENTS_MINIO_ACCESS_KEY" in line for line in lines)
    assert any("ATTACHMENTS_CLAMAV_HOST" in line for line in lines)
    assert any("ATTACHMENTS_IMAGE_OCR_MODEL" in line for line in lines)


def test_mode_report_reports_the_ocr_alias_when_it_is_wired() -> None:
    mod = _load_probe_module()
    env = {"ATTACHMENTS_IMAGE_OCR_BACKEND": "gateway", "ATTACHMENTS_IMAGE_OCR_MODEL": "tier-mid"}

    lines = mod.mode_report(env, blob="filesystem", scanner="disabled")

    assert "image_ocr_backend=gateway model=tier-mid" in lines
    assert not any(line.startswith("warn:") for line in lines)


def test_mode_report_is_quiet_when_the_full_launch_is_fully_configured() -> None:
    mod = _load_probe_module()
    env = {
        "ATTACHMENTS_MINIO_ACCESS_KEY": "key",
        "ATTACHMENTS_MINIO_SECRET_KEY": "secret",
        "ATTACHMENTS_CLAMAV_HOST": "clamav",
        "ATTACHMENTS_IMAGE_OCR_BACKEND": "gateway",
        "ATTACHMENTS_IMAGE_OCR_MODEL": "tier-mid",
    }

    lines = mod.mode_report(env, blob="minio", scanner="clamav", extra=["note: trailer"])

    assert lines == [
        "blob_backend=minio",
        "scanner_backend=clamav",
        "image_ocr_backend=gateway model=tier-mid",
        "note: trailer",
    ]


class _VirtualClock:
    """A clock that only moves when ``sleep`` is called — deterministic, no wall time."""

    def __init__(self) -> None:
        self.elapsed = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.elapsed

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.elapsed += seconds


class _ScriptedProbe:
    """A probe that fails a fixed number of times before it starts passing.

    The module's own ``Probe`` constructor is injected: the script is loaded by path
    (it is not a package), so this file cannot import from it at module scope.
    """

    def __init__(self, probe, name: str, *, fails_for: int) -> None:
        self._probe = probe
        self.name = name
        self.calls = 0
        self._fails_for = fails_for

    def __call__(self):
        self.calls += 1
        ok = self.calls > self._fails_for
        return self._probe(name=self.name, ok=ok, detail=f"{self.name} -> {'ok' if ok else 'not yet'}")


def test_run_until_ready_retries_only_the_probes_that_are_not_ready() -> None:
    """Readiness must not re-probe what already answered.

    Re-running a green store probe every iteration would turn clamd's 5-minute warm-up
    into 5 minutes of pointless S3 round-trips, and would make the timeout meaningless.
    """
    mod = _load_probe_module()
    clock = _VirtualClock()
    steady = _ScriptedProbe(mod.Probe, "s3", fails_for=0)
    warm = _ScriptedProbe(mod.Probe, "clamav", fails_for=1)
    cold = _ScriptedProbe(mod.Probe, "api", fails_for=2)
    announced: list[str] = []

    report = mod.run_until_ready(
        [steady, warm, cold],
        timeout=60.0,
        sleep=clock.sleep,
        clock=clock.now,
        announce=announced.append,
    )

    assert steady.calls == 1, "a probe that already passed must not be re-run"
    assert (warm.calls, cold.calls) == (2, 3)
    assert clock.slept == [mod._RETRY_DELAY_SECONDS, mod._RETRY_DELAY_SECONDS]
    assert not report.failed
    assert [probe.name for probe in report.probes] == ["s3", "clamav", "api"], (
        "each probe must be reported exactly once"
    )
    assert announced
    assert "clamav" in announced[0]


def test_run_until_ready_gives_up_at_the_deadline_and_reports_the_failures() -> None:
    """`make up` needs a bounded wait: an unreachable engine must fail loudly, not hang."""
    mod = _load_probe_module()
    clock = _VirtualClock()
    never = _ScriptedProbe(mod.Probe, "clamav", fails_for=10**9)

    report = mod.run_until_ready([never], timeout=10.0, sleep=clock.sleep, clock=clock.now)

    assert report.failed
    assert report.failed[0].name == "clamav"
    assert clock.elapsed == 10.0, "the deadline must bound the wait"
    # The last sleep is clamped to what is left of the deadline.
    assert clock.slept == [
        mod._RETRY_DELAY_SECONDS,
        mod._RETRY_DELAY_SECONDS,
        mod._RETRY_DELAY_SECONDS,
        1.0,
    ]


def test_run_until_ready_defaults_to_a_single_pass() -> None:
    """The plain `make attach-probe` must stay a snapshot, not a wait."""
    mod = _load_probe_module()
    clock = _VirtualClock()
    failing = _ScriptedProbe(mod.Probe, "api", fails_for=10**9)

    report = mod.run_until_ready([failing], sleep=clock.sleep, clock=clock.now)

    assert failing.calls == 1
    assert clock.slept == []
    assert report.failed


def _stub_compose_state(mod, monkeypatch, *, queried: bool, record: dict[str, object] | None) -> None:
    monkeypatch.setattr(mod, "_compose_service_state", lambda env_file, service: (queried, record))


def test_silo_bootstrap_accepts_a_finished_init_container(monkeypatch) -> None:
    """An exited init container is the expected end state, not a down service.

    This is the whole reason the bootstrap is a probe instead of ``up --wait``: compose
    and the Docker UI both show this container as *not running* after it succeeded, so
    "silo-init is not running" must never be reported as a failure.
    """
    mod = _load_probe_module()
    _stub_compose_state(
        mod,
        monkeypatch,
        queried=True,
        record={
            "State": "exited",
            "ExitCode": 0,
            "Name": "palatium-ai-silo-init-1",
            "Status": "Exited (0) 39 minutes ago",
        },
    )

    probe = mod.check_silo_bootstrap(Path("env/.env"))

    assert probe.ok
    assert "exited 0" in probe.detail
    assert probe.hint == ""


def test_silo_bootstrap_fails_when_the_one_shot_exited_non_zero(monkeypatch) -> None:
    """A broken bootstrap is invisible elsewhere: the API makes its own bucket anyway."""
    mod = _load_probe_module()
    _stub_compose_state(
        mod,
        monkeypatch,
        queried=True,
        record={
            "State": "exited",
            "ExitCode": 1,
            "Name": "palatium-ai-silo-init-1",
            "Status": "Exited (1) 2 minutes ago",
        },
    )

    probe = mod.check_silo_bootstrap(Path("env/.env"))

    assert not probe.ok
    assert "exit 1" in probe.detail
    # The consequence (empty tracing) and the next step both have to be in the hint.
    assert "langfuse" in probe.hint
    assert "logs silo-init" in probe.hint


def test_silo_bootstrap_reads_a_string_exit_code(monkeypatch) -> None:
    """Compose serialises the field as a number on some releases and a string on others."""
    mod = _load_probe_module()
    _stub_compose_state(
        mod,
        monkeypatch,
        queried=True,
        record={"State": "exited", "ExitCode": "0", "Name": "palatium-ai-silo-init-1", "Status": "Exited (0)"},
    )

    assert mod.check_silo_bootstrap(Path("env/.env")).ok


def test_silo_bootstrap_is_retryable_while_the_one_shot_is_still_running(monkeypatch) -> None:
    """Not finished is a "not yet" for `--wait`, never a verdict about the stack."""
    mod = _load_probe_module()
    _stub_compose_state(
        mod,
        monkeypatch,
        queried=True,
        record={"State": "running", "ExitCode": 0, "Name": "palatium-ai-silo-init-1", "Status": "Up 1 second"},
    )

    probe = mod.check_silo_bootstrap(Path("env/.env"))

    assert not probe.ok
    assert "not finished" in probe.detail


def test_silo_bootstrap_is_not_a_verdict_when_the_profile_created_no_container(monkeypatch) -> None:
    """No init container means the S3/observability profile was not in this launch.

    Failing here would make `--wait` spin on a service that will never appear, and the
    store probe already reports that launch on its own.
    """
    mod = _load_probe_module()
    _stub_compose_state(mod, monkeypatch, queried=True, record=None)

    probe = mod.check_silo_bootstrap(Path("env/.env"))

    assert probe.ok
    assert "not created" in probe.detail


def test_silo_bootstrap_does_not_blame_the_stack_when_compose_is_unavailable(monkeypatch) -> None:
    """The probe runs from `make` and must not hard-fail without a usable daemon."""
    mod = _load_probe_module()
    _stub_compose_state(mod, monkeypatch, queried=False, record=None)

    probe = mod.check_silo_bootstrap(Path("env/.env"))

    assert probe.ok
    assert "not checked" in probe.detail


def test_compose_records_accepts_both_ps_shapes() -> None:
    """NDJSON is what 5.5.1 prints; the array form is what older releases printed."""
    mod = _load_probe_module()

    assert mod._compose_records('[{"State": "exited"}, {"State": "running"}]') == [
        {"State": "exited"},
        {"State": "running"},
    ]
    assert mod._compose_records('{"State": "exited"}\n{"State": "running"}') == [
        {"State": "exited"},
        {"State": "running"},
    ]
    assert mod._compose_records("") == []
    assert mod._compose_records("not json at all") == []


def _compose_state_from_records(mod, monkeypatch, records: list[dict[str, object]]):
    """Drive ``_compose_service_state`` from a canned ``compose ps`` payload.

    Only the low-level pieces are stubbed, so ``check_silo_bootstrap`` runs its real
    selection logic on top of them.
    """
    monkeypatch.setattr(mod.shutil, "which", lambda name: "docker")
    monkeypatch.setattr(mod, "_compose_records", lambda output: records)

    class _Result:
        returncode = 0
        stdout = "stub"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: _Result())
    return mod._compose_service_state(Path("env/.env"), mod._SILO_INIT_SERVICE)


def _ps_record(*, name: str, state: str, exit_code: int, one_off: bool) -> dict[str, object]:
    return {
        "Name": name,
        "State": state,
        "ExitCode": exit_code,
        "Status": f"{state} ({exit_code})",
        "Labels": (f"com.docker.compose.service=silo-init,com.docker.compose.oneoff={'True' if one_off else 'False'}"),
    }


def test_one_off_run_containers_are_not_the_managed_bootstrap(monkeypatch) -> None:
    """`ps -a` lists `compose run` containers next to the real one — verified on 5.5.1.

    A manual `docker compose run silo-init` that exited non-zero is an operator action,
    so letting it verdict the launch would fail a perfectly healthy stack. The one-off is
    placed first on purpose: taking the first record instead of the managed one is the
    bug this pins.
    """
    mod = _load_probe_module()
    records = [
        _ps_record(name="palatium-ai-silo-init-run-ab12", state="exited", exit_code=3, one_off=True),
        _ps_record(name="palatium-ai-silo-init-1", state="exited", exit_code=0, one_off=False),
    ]

    queried, record = _compose_state_from_records(mod, monkeypatch, records)

    assert queried
    assert record == records[1]
    assert mod.check_silo_bootstrap(Path("env/.env")).ok


def test_a_lone_one_off_container_does_not_count_as_the_bootstrap(monkeypatch) -> None:
    """Only the managed init container answers for the launch; `run` is not a substitute."""
    mod = _load_probe_module()
    records = [_ps_record(name="palatium-ai-silo-init-run-ab12", state="exited", exit_code=0, one_off=True)]

    queried, record = _compose_state_from_records(mod, monkeypatch, records)

    assert queried
    assert record is None
    assert "not created" in mod.check_silo_bootstrap(Path("env/.env")).detail


def _stub_named_checks(mod, monkeypatch) -> None:
    """Replace every check ``_checks`` builds so the wiring can be asserted by name."""

    def _factory(name: str):
        def _check(*args, **kwargs):
            return mod.Probe(name=name, ok=True, detail="stub")

        return _check

    for function, name in (
        ("check_s3", "s3"),
        ("check_silo_bootstrap", "silo-init"),
        ("check_clamav", "clamav"),
        ("check_api", "api"),
    ):
        monkeypatch.setattr(mod, function, _factory(name))


def _run_checks(mod, *, skip_s3: bool) -> list[str]:
    factories = mod._checks(
        env_file=Path("env/.env"),
        image="img",
        public_raw="localhost:9000",
        clamav_host="localhost",
        clamav_port=3310,
        api_url="http://127.0.0.1:8000",
        preflight=False,
        skip_s3=skip_s3,
        skip_clamav=False,
        skip_api=False,
    )
    return [factory().name for factory in factories]


def test_bootstrap_is_probed_together_with_the_store(monkeypatch) -> None:
    mod = _load_probe_module()
    _stub_named_checks(mod, monkeypatch)

    assert _run_checks(mod, skip_s3=False) == ["s3", "silo-init", "clamav", "api"]


def test_bootstrap_is_skipped_with_the_store(monkeypatch) -> None:
    """`--skip-s3` marks a run that never recreates the init container (`make rebuild-app`)."""
    mod = _load_probe_module()
    _stub_named_checks(mod, monkeypatch)

    assert _run_checks(mod, skip_s3=True) == ["clamav", "api"]
