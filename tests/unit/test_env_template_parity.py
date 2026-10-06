"""Env-template parity guard (010, 050, 055).

``env/.env.example`` is documented as the single complete reference ("Канон ключей =
env/.env.example"), and every profile promises the same key set. In practice the
profiles drifted up to 91 keys behind the canon, so a key that an operator believed
was configured silently fell back to a pydantic default instead.

The guard is generic — it derives the expected key set from the code itself, so it
covers any future key rather than the ones that happened to be missing today:

* **completeness** — every ``Settings`` knob (explicit ``validation_alias``) must
  appear in every tracked ``env/*.example`` template;
* **no strays** — every key in any env file must be a real knob, a compose variable,
  or one of the documented non-``Settings`` keys below. A typo or a key that survived
  a rename is otherwise invisible.
"""

from __future__ import annotations

import re

from pathlib import Path
from urllib.parse import urlsplit

import pytest

from pydantic import BaseModel
from pydantic.fields import FieldInfo

from palatium_ai.core.config.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
ENV_DIR = REPO_ROOT / "env"
COMPOSE_FILES = (
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.override.yml",
    REPO_ROOT / "deploy" / "observability" / "compose.observability.yml",
)

_KEY_LINE = re.compile(r"^\s*(?:#\s*)?([A-Z][A-Z0-9_]*)=")
_COMPOSE_VAR = re.compile(r"\$\{([A-Z][A-Z0-9_]*)(?::-[^}]*)?\}")

# Keys that are deliberately NOT pydantic Settings knobs. Each is read outside the
# config model, so it cannot be discovered by introspection. Keep this list short:
# a new entry is a conscious decision, which is the point of the guard.
NON_SETTINGS_KEYS: frozenset[str] = frozenset(
    {
        # core/observability/audit.py (os.getenv): hash-chained audit log.
        "AUDIT_LOG_FILE",
        "AUDIT_HMAC_SECRET",
        # scripts/archive_mcp_tool_calls.py + purge/retention_report (offline CLI).
        "MCP_RETENTION_ARCHIVE_DAYS",
        "MCP_RETENTION_PURGE_YEARS",
        "MCP_RETENTION_BATCH_SIZE",
        "MCP_RETENTION_EVENT",
        "MCP_RETENTION_SERVER_NAME",
        "MCP_RETENTION_IS_ERROR",
        "MCP_RETENTION_EXECUTE",
        # LiteLLM gateway process + its UI (deploy/litellm/config.yaml, compose).
        "LITELLM_MASTER_KEY",
        "LITELLM_DB_URL",
        "LITELLM_LOG",
        "UI_USERNAME",
        "UI_PASSWORD",
        # Optional MCP proxy profile (docker-compose --profile mcp-gateway).
        "MCP_GATEWAY_SERVER",
        "MCP_UPSTREAM_URL",
        "MCP_UPSTREAM_BEARER",
        "MCP_UPSTREAM_HTTP_ALLOWED_HOSTS",
        # Optional Langfuse overlay (deploy/observability).
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_HOST",
        "LANGFUSE_DB_URL",
        "LANGFUSE_PUBLISH_PORT",
        "LANGFUSE_NEXTAUTH_SECRET",
        "LANGFUSE_SALT",
        "LANGFUSE_NEXTAUTH_URL",
        # Langfuse **v3** dependencies. v3 keeps traces in ClickHouse and queues
        # ingestion through Valkey, so the profile needs credentials those containers
        # cannot invent themselves. Everything structural (ClickHouse URL/user/db, S3
        # bucket, org/project labels) is a literal in docker-compose.yml on purpose:
        # each extra compose variable would have to be declared in every profile
        # template, and those values are not meant to vary per environment.
        # Compose reads these through ${VAR:?…} (fail-closed), which the compose-var
        # regex above does not match — hence the explicit entries.
        "CLICKHOUSE_PASSWORD",
        "LANGFUSE_ENCRYPTION_KEY",
        "LANGFUSE_INIT_USER_PASSWORD",
        # Prometheus/Grafana overlay.
        "PROMETHEUS_PUBLISH_PORT",
        "PROMETHEUS_RETENTION",
        "PROMETHEUS_METRICS_TOKEN",
        "ALERTMANAGER_PUBLISH_PORT",
        "GRAFANA_PUBLISH_PORT",
        "GRAFANA_ADMIN_USER",
        "GRAFANA_ADMIN_PASSWORD",
        "GRAFANA_ROOT_URL",
        "LOKI_PUBLISH_PORT",
    }
)

# PALATIUM_EVAL_* drives the nightly eval runners (040, docs/agent-evals.md).
NON_SETTINGS_PREFIXES: tuple[str, ...] = ("PALATIUM_EVAL_",)


def _settings_keys() -> set[str]:
    """Every env knob the app reads: explicit ``validation_alias`` only.

    A field without an alias is internal (e.g. ``GatewayLLMConfig.provider_name``)
    and inventing ``NAME.upper()`` for it would assert keys the app never reads.
    """
    found: set[str] = set()

    def walk(model: type[BaseModel]) -> None:
        for info in model.model_fields.values():
            annotation = info.annotation
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                walk(annotation)
                continue
            alias = info.validation_alias if isinstance(info, FieldInfo) else None
            if isinstance(alias, str):
                found.add(alias)

    walk(Settings)
    return found


def _compose_keys() -> set[str]:
    keys: set[str] = set()
    for path in COMPOSE_FILES:
        if path.is_file():
            keys |= set(_COMPOSE_VAR.findall(path.read_text(encoding="utf-8")))
    return keys


def _declared_keys(path: Path) -> set[str]:
    """Keys in the file, including commented-out ones (documented == declared)."""
    return {m.group(1) for m in (_KEY_LINE.match(line) for line in _lines(path)) if m}


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _env_files() -> list[Path]:
    return sorted(p for p in ENV_DIR.glob(".env*") if p.is_file())


def _templates() -> list[Path]:
    # Only *.example is tracked; the working profiles are gitignored and may be absent.
    return sorted(ENV_DIR.glob(".env*.example"))


def test_the_canonical_template_exists() -> None:
    assert (ENV_DIR / ".env.example").is_file(), "env/.env.example is the documented canon"


def _canonical_keys() -> set[str]:
    """Every key the canon is documented to carry (docstring: canon == full key set).

    ``Settings`` alone is not the contract: an operator reads a profile template as
    "the keys this deployment needs", and a missing infra key (LiteLLM DB, MinIO
    image, observability overlay) fails at container start rather than at import.
    """
    return _settings_keys() | _compose_keys() | NON_SETTINGS_KEYS


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_every_template_declares_every_setting(template: Path) -> None:
    """A missing key means the profile silently runs on a pydantic default."""
    missing = sorted(_settings_keys() - _declared_keys(template))
    assert not missing, f"{template.name} is missing {len(missing)} key(s): {', '.join(missing)}"


@pytest.mark.parametrize("template", _templates(), ids=lambda p: p.name)
def test_every_template_declares_the_full_canon(template: Path) -> None:
    """Profile templates must be drop-in complete, not just ``Settings``-complete."""
    missing = sorted(_canonical_keys() - _declared_keys(template))
    assert not missing, f"{template.name} is missing {len(missing)} canon key(s): {', '.join(missing)}"


@pytest.mark.skipif(not _env_files(), reason="no env files checked out")
@pytest.mark.parametrize("env_file", _env_files(), ids=lambda p: p.name)
def test_env_files_contain_no_stray_keys(env_file: Path) -> None:
    """A typo / renamed key is otherwise indistinguishable from an unset one."""
    known = _settings_keys() | _compose_keys() | NON_SETTINGS_KEYS
    strays = sorted(
        key for key in _declared_keys(env_file) if key not in known and not key.startswith(NON_SETTINGS_PREFIXES)
    )
    assert not strays, f"{env_file.name} has unknown key(s): {', '.join(strays)}"


def test_working_profiles_match_their_template() -> None:
    """``.env.staging``/``.env.prod`` are copies of their template (documented workflow).

    Compared on the key set only: the working copy may hold injected secrets, but it
    must not lag behind the template's key set.
    """
    pairs = ((".env.staging", ".env.staging.example"), (".env.prod", ".env.prod.example"))
    for working_name, template_name in pairs:
        working, template = ENV_DIR / working_name, ENV_DIR / template_name
        if not working.is_file():
            pytest.skip(f"{working_name} not checked out")
        missing = sorted(_declared_keys(template) - _declared_keys(working))
        assert not missing, f"{working_name} lags {template_name}: {', '.join(missing)}"


@pytest.mark.parametrize(
    "profile_name",
    (".env", ".env.dev", ".env.staging", ".env.prod"),
)
def test_working_profile_declares_every_setting(profile_name: str) -> None:
    """The concrete profiles must be as complete as the canon, key for key.

    ``test_every_template_declares_every_setting`` only covers ``*.example`` and
    ``test_working_profiles_match_their_template`` only diffs staging/prod against
    their own template — so a knob missing from ``.env``/``.env.dev`` used to be
    invisible: the operator believes it is configured while the app silently falls
    back to the pydantic default.
    """
    profile = ENV_DIR / profile_name
    if not profile.is_file():
        pytest.skip(f"{profile_name} not checked out")
    missing = sorted(_settings_keys() - _declared_keys(profile))
    assert not missing, f"{profile_name} is missing {len(missing)} key(s): {', '.join(missing)}"


def test_non_settings_allowlist_has_no_dead_entries() -> None:
    """Keep the escape hatch honest: every allowlisted key must be declared somewhere."""
    declared: set[str] = set()
    for env_file in _env_files():
        declared |= _declared_keys(env_file)
    if not declared:
        pytest.skip("no env files checked out")
    dead = sorted(NON_SETTINGS_KEYS - declared)
    assert not dead, f"NON_SETTINGS_KEYS contains undeclared key(s): {', '.join(dead)}"


def test_introspection_actually_finds_the_config_surface() -> None:
    """Anti-vacuous guard: if aliases were dropped, completeness would pass trivially."""
    keys = _settings_keys()
    assert len(keys) > 100, f"introspection collapsed to {len(keys)} keys"
    assert "ATTACHMENTS_ENABLED" in keys


#: Templates whose MinIO endpoint is the *local* stack (staging/prod point at a real
#: store and leave the public endpoint for the operator to fill in).
_LOCAL_STORE_TEMPLATES = (".env", ".env.dev", ".env.example", ".env.local.example", ".env.cloud.example")


@pytest.mark.parametrize("profile_name", _LOCAL_STORE_TEMPLATES)
def test_browser_facing_store_endpoint_is_a_bound_loopback_literal(profile_name: str) -> None:
    """``localhost`` in the presigned URL costs ~2 s per upload on Windows (020).

    The local store publishes ``127.0.0.1:9000`` only — bound to the IPv4 loopback on
    purpose, since the object store must not be reachable from the LAN. Windows
    resolves ``localhost`` to ``::1`` first, finds nothing there, and *then* falls back
    to IPv4, which measured 2072 ms per request versus 2 ms for the literal. The
    browser pays that on every presigned PUT, and the address cannot be patched after
    signing (SigV4 covers ``Host``, runbook §16.4), so it has to be right in the
    template.
    """
    profile = ENV_DIR / profile_name
    if not profile.is_file():
        pytest.skip(f"{profile_name} not checked out")

    value = next(
        (
            match.group(1)
            for line in _lines(profile)
            if (match := re.match(r'^\s*ATTACHMENTS_MINIO_PUBLIC_ENDPOINT="?([^"#\s]+)', line))
        ),
        None,
    )
    if value is None:
        pytest.skip(f"{profile_name} leaves the browser-facing endpoint unset")

    host = urlsplit(value).hostname
    assert host == "127.0.0.1", (
        f"{profile_name}: ATTACHMENTS_MINIO_PUBLIC_ENDPOINT host is {host!r}; "
        "use the loopback literal the port is actually published on (see runbook §16.9)"
    )
