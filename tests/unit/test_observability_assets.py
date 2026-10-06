"""Observability assets are a contract, not prose (040, P1-7).

Everything in ``deploy/observability/`` is executed by tools we do not run in unit
tests: Prometheus, Alertmanager, Grafana, Loki. A typo in a metric name or a
malformed rule file fails *silently in production* — the alert simply never fires.

These tests close that gap by checking the assets against the one thing we do own:
the metric registry in ``core/observability/metrics.py``.
"""

from __future__ import annotations

import json
import re

from pathlib import Path
from typing import Any

import pytest
import yaml

# Importing the module is what registers the metrics in the default registry.
import palatium_ai.core.observability.metrics  # noqa: F401

_OBSERVABILITY_DIR = Path(__file__).resolve().parents[2] / "deploy" / "observability"
_ALERTS_DIR = _OBSERVABILITY_DIR / "prometheus" / "alerts"
_DASHBOARD = _OBSERVABILITY_DIR / "grafana" / "dashboards" / "palatium-overview.json"
_PROMETHEUS_CONFIG = _OBSERVABILITY_DIR / "prometheus" / "prometheus.yml"
_ALERTMANAGER_CONFIG = _OBSERVABILITY_DIR / "alertmanager" / "alertmanager.yml"

# Only app metrics are validated. `up`, `le`, `rate`, … are Prometheus built-ins.
_APP_METRIC_RE = re.compile(r"\bpalatium_[a-z0-9_]+\b")

# Sample suffixes added by prometheus_client on top of the family name.
_SAMPLE_SUFFIXES = ("_bucket", "_sum", "_count", "_created", "_total")

_KNOWN_SEVERITIES = {"critical", "warning", "info"}


def _registered_metric_names() -> set[str]:
    """Names declared in the app registry, in both family and sample spelling.

    ``Counter("x_total")`` registers a family named ``x``, so both spellings are
    accepted; that keeps alert expressions (which use ``_total``) valid.
    """
    from prometheus_client import REGISTRY

    names: set[str] = set()
    for metric in REGISTRY.collect():
        names.add(metric.name)
        names.add(f"{metric.name}_total")
    return names


def _is_registered(name: str, registered: set[str]) -> bool:
    if name in registered:
        return True
    return any(name.endswith(suffix) and name[: -len(suffix)] in registered for suffix in _SAMPLE_SUFFIXES)


def _app_metrics_in(expr: str) -> set[str]:
    return set(_APP_METRIC_RE.findall(expr))


def _alert_files() -> list[Path]:
    return sorted(_ALERTS_DIR.glob("*.yml"))


def _load_yaml(path: Path) -> dict[str, Any]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path.name} must parse to a mapping"
    return loaded


def _iter_rules() -> list[tuple[str, dict[str, Any]]]:
    """Yield ``(source_file, rule)`` for every recording and alerting rule."""
    rules: list[tuple[str, dict[str, Any]]] = []
    for path in _alert_files():
        document = _load_yaml(path)
        for group in document.get("groups", []):
            group_name = group.get("name", "<unnamed>")
            rules.extend((f"{path.name}:{group_name}", rule) for rule in group.get("rules", []))
    return rules


def _dashboard_panel_exprs() -> list[tuple[str, str]]:
    dashboard = json.loads(_DASHBOARD.read_text(encoding="utf-8"))
    exprs: list[tuple[str, str]] = []
    for panel in dashboard.get("panels", []):
        for target in panel.get("targets", []):
            expr = target.get("expr")
            if isinstance(expr, str):
                exprs.append((panel.get("title", "<untitled>"), expr))
    return exprs


def test_alert_rule_files_exist_and_parse() -> None:
    files = _alert_files()
    assert files, f"no alert rule files found in {_ALERTS_DIR}"
    rules = _iter_rules()
    assert rules, "alert rule files contain no rules"


def test_every_promql_app_metric_exists_in_registry() -> None:
    """A typo'd metric name must fail CI, not silently never fire."""
    registered = _registered_metric_names()
    assert registered, "app registry is empty — prometheus_client missing?"

    missing: list[str] = []
    for source, rule in _iter_rules():
        missing.extend(
            f"{source}: {name}"
            for name in _app_metrics_in(str(rule.get("expr", "")))
            if not _is_registered(name, registered)
        )
    assert not missing, "alert rules reference unknown app metrics:\n" + "\n".join(missing)


def test_dashboard_panels_reference_known_app_metrics() -> None:
    registered = _registered_metric_names()
    missing: list[str] = []
    for title, expr in _dashboard_panel_exprs():
        missing.extend(f"{title}: {name}" for name in _app_metrics_in(expr) if not _is_registered(name, registered))
    assert not missing, "dashboard panels reference unknown app metrics:\n" + "\n".join(missing)


def test_every_alert_is_actionable() -> None:
    """An alert without severity/for/summary is either noise or invisible."""
    problems: list[str] = []
    for source, rule in _iter_rules():
        alert = rule.get("alert")
        if alert is None:  # recording rule
            assert rule.get("record"), f"{source}: rule has neither 'alert' nor 'record'"
            continue
        if not str(rule.get("expr", "")).strip():
            problems.append(f"{source}/{alert}: empty expr")
        if not rule.get("for"):
            problems.append(f"{source}/{alert}: no 'for' — instant flapping alert")
        severity = (rule.get("labels") or {}).get("severity")
        if severity not in _KNOWN_SEVERITIES:
            problems.append(f"{source}/{alert}: severity {severity!r} not in {sorted(_KNOWN_SEVERITIES)}")
        if not (rule.get("annotations") or {}).get("summary"):
            problems.append(f"{source}/{alert}: missing annotations.summary")
    assert not problems, "unactionable alerts:\n" + "\n".join(problems)


def test_alertmanager_routes_every_declared_severity() -> None:
    """A severity no route matches falls back to the default receiver silently."""
    declared = {(rule.get("labels") or {}).get("severity") for _, rule in _iter_rules() if rule.get("alert")}
    document = _load_yaml(_ALERTMANAGER_CONFIG)
    route = document.get("route", {})
    routed: set[str] = set()
    for entry in route.get("routes", []):
        for matcher in entry.get("matchers", []):
            match = re.match(r'\s*severity\s*=~?\s*"([^"]+)"', str(matcher))
            if match:
                routed.update(re.split(r"\|", match.group(1)))
    unmatched = {s for s in declared if s and s not in routed}
    assert not unmatched, f"severities with no Alertmanager route (silent): {sorted(unmatched)}"


def test_prometheus_scrapes_api_metrics_with_bearer_token() -> None:
    """staging/production forces metrics_public=false, so the scrape must authenticate."""
    document = _load_yaml(_PROMETHEUS_CONFIG)
    jobs = {job.get("job_name"): job for job in document.get("scrape_configs", [])}
    api_job = jobs.get("palatium-api")
    assert api_job is not None, f"palatium-api scrape job missing; found: {sorted(jobs)}"
    assert api_job.get("metrics_path") == "/metrics"
    authorization = api_job.get("authorization") or {}
    assert authorization.get("credentials_file"), "scrape job must send a bearer token file"


def test_prometheus_loads_alert_rules_from_mounted_dir() -> None:
    document = _load_yaml(_PROMETHEUS_CONFIG)
    rule_files = document.get("rule_files", [])
    assert any("alerts" in str(entry) for entry in rule_files), f"rule_files does not include alerts dir: {rule_files}"


@pytest.mark.parametrize("path", (*sorted(_ALERTS_DIR.glob("*.yml")), _PROMETHEUS_CONFIG, _ALERTMANAGER_CONFIG))
def test_yaml_assets_parse(path: Path) -> None:
    assert _load_yaml(path)


def test_compose_overlay_binds_loopback_only() -> None:
    """020: the observability stack must never listen on a public interface."""
    overlay = _load_yaml(_OBSERVABILITY_DIR / "compose.observability.yml")
    offenders: list[str] = []
    for name, service in overlay.get("services", {}).items():
        offenders.extend(
            f"{name}: {mapping}" for mapping in service.get("ports", []) if not str(mapping).startswith("127.0.0.1:")
        )
    assert not offenders, "observability ports must bind 127.0.0.1:\n" + "\n".join(offenders)
