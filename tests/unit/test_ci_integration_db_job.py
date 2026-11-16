"""CI contract: the Postgres jobs exist and cannot degrade silently (082, 075).

The durable extract queue (M3) is SQL — ``FOR UPDATE SKIP LOCKED``, lease renew, the
``dead`` transition, atomic enqueue. All of it was unverified in CI because
``tests/integration`` skipped whenever ``DATABASE_URL`` was absent, and *every* CI job
lacked it: the suite reported green while testing nothing. Rules make the wiring a
contract rather than a habit, so this file pins:

* the integration job exists, brings its own Postgres, and runs the integration suite;
* the memory query p95 job exists, migrates first, and runs the pgvector latency eval;
* every workflow Postgres service uses the *same digest* as ``docker-compose.yml`` (025) —
  an independently drifting pin is exactly the failure 025 forbids;
* ``PALATIUM_REQUIRE_DB=1`` is set, so a lost ``DATABASE_URL`` fails the job instead of
  quietly restoring the skip.
"""

from __future__ import annotations

import importlib.util

from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
PERF_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "perf-nightly.yml"
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
INTEGRATION_CONFTEST = REPO_ROOT / "tests" / "integration" / "conftest.py"

_JOB = "integration-db"
_LATENCY_JOB = "memory-query-latency"
_LATENCY_TEST = "tests/perf/test_memory_query_latency.py"


def _workflow() -> dict[str, Any]:
    loaded = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "ci.yml must parse to a mapping"
    return loaded


def _job() -> dict[str, Any]:
    jobs: dict[str, Any] = _workflow().get("jobs", {})
    assert _JOB in jobs, f"CI job {_JOB!r} is missing: the Postgres SQL paths have no gate"
    job = jobs[_JOB]
    assert isinstance(job, dict), f"job {_JOB!r} must be a mapping"
    return job


def _job_env() -> dict[str, str]:
    env = _job().get("env", {})
    assert isinstance(env, dict), f"job {_JOB!r} must declare env"
    return {str(key): str(value) for key, value in env.items()}


def _run_commands() -> list[str]:
    """Every ``run:`` body of the job, in declaration order."""
    steps = [step for step in _job().get("steps", []) if isinstance(step, dict) and "run" in step]
    return [str(step["run"]) for step in steps]


def _compose_postgres_image() -> str:
    compose = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    return str(compose["services"]["postgres"]["image"])


def test_job_runs_the_integration_suite_against_postgres() -> None:
    commands = _run_commands()
    assert any("pytest" in command and "tests/integration" in command for command in commands), (
        f"job {_JOB!r} must run tests/integration, otherwise the queue/graph SQL stays untested"
    )
    services = _job().get("services", {})
    assert "postgres" in services, f"job {_JOB!r} must provide a postgres service"


def test_migrations_run_before_the_tests() -> None:
    """Schema from migrations, never from test code (075): otherwise the suite passes on a schema prod lacks."""
    commands = _run_commands()
    migrations = next((i for i, command in enumerate(commands) if "alembic upgrade head" in command), None)
    tests = next((i for i, command in enumerate(commands) if "tests/integration" in command), None)
    assert migrations is not None, f"job {_JOB!r} must run `alembic upgrade head`"
    assert tests is not None
    assert migrations < tests, "migrations must run before the integration tests"


def test_service_image_shares_the_compose_digest() -> None:
    """025: one image, one pin. A second hand-maintained digest is drift waiting to happen."""
    service = _job()["services"]["postgres"]
    image = str(service["image"])
    assert "@sha256:" in image, f"service image must be digest-pinned (025): {image!r}"
    assert image == _compose_postgres_image(), (
        f"the CI service image must be the exact docker-compose.yml pin; ci={image!r} compose={_compose_postgres_image()!r}"
    )


def test_missing_database_url_fails_instead_of_skipping() -> None:
    """The whole point of E4b: absence of a DB must be red, not a silently skipped suite."""
    assert _job_env().get("PALATIUM_REQUIRE_DB") == "1"


def test_database_url_matches_the_service_credentials() -> None:
    """Alembic reads POSTGRES_*, the tests read DATABASE_URL — disagreeing pairs fail at run time."""
    env = _job_env()
    service_env = _job()["services"]["postgres"]["env"]

    dsn = urlsplit(env["DATABASE_URL"])
    assert dsn.scheme == "postgresql+asyncpg"
    assert dsn.hostname == env["POSTGRES_HOST"], "DATABASE_URL and POSTGRES_HOST must point at the same DB"
    assert dsn.port == int(env["POSTGRES_PORT"]), "DATABASE_URL and POSTGRES_PORT must agree"
    assert dsn.username == env["POSTGRES_USER"] == str(service_env["POSTGRES_USER"])
    assert dsn.password == env["POSTGRES_PASSWORD"] == str(service_env["POSTGRES_PASSWORD"])
    assert dsn.path.lstrip("/") == env["POSTGRES_DB"] == str(service_env["POSTGRES_DB"])

    # The published host port is what the job (running on the runner, not in the service
    # container) actually dials; a mismatch here is a connection-refused at run time.
    published = [str(entry) for entry in _job()["services"]["postgres"]["ports"]]
    assert f"{env['POSTGRES_PORT']}:5432" in published, (
        f"postgres service ports {published} do not publish POSTGRES_PORT={env['POSTGRES_PORT']}"
    )


def _load_integration_conftest() -> Any:
    spec = importlib.util.spec_from_file_location("_integration_conftest_contract", INTEGRATION_CONFTEST)
    assert spec is not None, "integration conftest must be loadable from disk"
    assert spec.loader is not None, "integration conftest must be loadable from disk"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("value", ("1", "true", "YES", " 1 "))
def test_require_database_flag_accepts_explicit_truthy_values(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("PALATIUM_REQUIRE_DB", value)
    assert _load_integration_conftest()._require_database_enabled() is True


@pytest.mark.parametrize("value", ("", "0", "false", "no"))
def test_require_database_flag_defaults_to_skipping(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Local runs without a database must keep skipping — only the owning job opts in."""
    monkeypatch.setenv("PALATIUM_REQUIRE_DB", value)
    assert _load_integration_conftest()._require_database_enabled() is False


def _jobs(workflow: Path) -> dict[str, dict[str, Any]]:
    loaded = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{workflow.name} must parse to a mapping"
    jobs = loaded.get("jobs", {})
    assert isinstance(jobs, dict), f"{workflow.name} must declare jobs"
    return {str(name): job for name, job in jobs.items() if isinstance(job, dict)}


def _postgres_image(job: dict[str, Any]) -> str | None:
    services = job.get("services", {})
    if not isinstance(services, dict):
        return None
    postgres = services.get("postgres", {})
    if not isinstance(postgres, dict):
        return None
    image = postgres.get("image")
    return None if image is None else str(image)


def test_every_workflow_postgres_service_shares_the_compose_digest() -> None:
    """025: one image, one pin — not one pin per workflow that happens to need a database."""
    expected = _compose_postgres_image()
    offenders = [
        f"{workflow.name}:{job_name}={image!r}"
        for workflow in sorted(WORKFLOWS_DIR.glob("*.yml"))
        for job_name, job in _jobs(workflow).items()
        if (image := _postgres_image(job)) is not None and image != expected
    ]
    assert not offenders, f"workflow Postgres services must use the docker-compose.yml pin {expected!r}: {offenders}"


def test_latency_job_owns_a_database_and_runs_the_p95_eval() -> None:
    """The p95 gate is only a gate if its job actually reaches a pgvector cluster (060, 075)."""
    jobs = _jobs(PERF_WORKFLOW)
    assert _LATENCY_JOB in jobs, f"{PERF_WORKFLOW.name} must run the memory query latency eval"
    job = jobs[_LATENCY_JOB]

    assert _postgres_image(job) is not None, f"job {_LATENCY_JOB!r} must provide a postgres service"
    commands = [str(step["run"]) for step in job.get("steps", []) if isinstance(step, dict) and "run" in step]
    latency = next((index for index, command in enumerate(commands) if _LATENCY_TEST in command), None)
    migrations = next((index for index, command in enumerate(commands) if "alembic upgrade head" in command), None)
    assert latency is not None, f"job {_LATENCY_JOB!r} must run {_LATENCY_TEST}"
    assert migrations is not None, f"job {_LATENCY_JOB!r} must run `alembic upgrade head`"
    assert migrations < latency, "migrations must run before the latency eval"

    env = job.get("env", {})
    assert isinstance(env, dict)
    assert {str(key): str(value) for key, value in env.items()}.get("PALATIUM_REQUIRE_DB") == "1"
