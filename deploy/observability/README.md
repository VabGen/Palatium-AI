# Observability stack (P1-7)

Prometheus + Alertmanager + Grafana + Loki/Promtail for local and staging use.

```
deploy/observability/
├── compose.observability.yml        # overlay on the main docker-compose.yml
├── SLO.md                           # SLI/SLO map → alerts, incl. what is NOT monitored
├── prometheus/
│   ├── prometheus.yml               # scrape config
│   └── alerts/                      # recording + alert rules (SLO, security, platform)
├── alertmanager/alertmanager.yml
├── grafana/
│   ├── provisioning/                # datasources + dashboard provider
│   └── dashboards/palatium-overview.json
├── loki/loki-config.yml
└── promtail/promtail-config.yml
```

## Run

```bash
# 1. Grafana refuses to start without an admin password (no default password in git).
#    Add these to env/.env (gitignored):
#      GRAFANA_ADMIN_PASSWORD=<local-only-password>
#
# 2. Start the full stack + observability overlay:
docker compose --env-file env/.env \
  -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  up -d --build
```

| Service | URL | Notes |
|---|---|---|
| Prometheus | http://localhost:9090 | targets: `/targets`, rules: `/rules` |
| Alertmanager | http://localhost:9093 | default receiver is a no-op — see below |
| Grafana | http://localhost:3000 | dashboard *Palatium AI — Overview* |
| Loki | http://localhost:3100 | query via Grafana Explore |

Everything binds to `127.0.0.1` only (020: nothing exposed on the perimeter).

## The `/metrics` scrape token

`presentation/app.py` computes:

```python
metrics_public = security.metrics_public if app.environment == "development" else False
```

So:

* **development** — `/metrics` is public; the bearer in `prometheus.yml` is ignored.
* **staging / production** — `/metrics` requires a **verified JWT**, regardless of
  `METRICS_PUBLIC`. Mint a long-lived scrape token and put it in `env/.env`:

  ```bash
  PROMETHEUS_METRICS_TOKEN=<jwt signed with JWT_SECRET>
  ```

The value is injected as an inline compose `config` and mounted read-only at
`/etc/prometheus/secrets/metrics_token`. Nothing is committed as a secret.

## What is intentionally NOT scraped

* **MCP stubs** (`mcp-edms`, `mcp-analytics`) expose `GET /health` but **no
  `/metrics`**. Scraping them would only produce permanent `up=0` noise. To monitor
  their liveness, add `prom/blackbox-exporter` and probe `/health` — a separate
  task, not a fake scrape job.

## Alerts

Rules live in `prometheus/alerts/` and are **contract-tested**: every
`palatium_*` metric referenced by an alert or dashboard must exist in
`core/observability/metrics.py`. A typo fails CI instead of silently never firing:

```bash
poetry run pytest tests/unit/test_observability_assets.py -q
```

Routing is deliberately inert out of the box — the `default` receiver is
Alertmanager's `null` type. Uncomment a real receiver in `alertmanager.yml`
(webhook / Slack) before depending on it. Secrets come from the environment.

## Production notes

1. **Pin image digests.** The compose file pins tags that are known to exist;
   production should pin `@sha256:` digests. Dependabot (`docker` ecosystem) keeps
   them fresh.
2. **Retention.** Prometheus `PROMETHEUS_RETENTION` (default `15d`) and Loki's
   `retention_period: 168h` are bounded on purpose. Long-term audit evidence
   belongs in the hash-chained audit log (040), not in Loki.
3. **Cardinality.** `trace_id` is a Loki *field*, never a label (040: ≤1000 series
   per metric). The Grafana dashboard filters on it via `| json | trace_id="…"`.
4. **TLS / auth.** This stack speaks plain HTTP on loopback. Terminate TLS and put
   it behind your ingress/auth proxy outside local dev.
5. **Log shipping is host-specific.** Promtail reads `/var/lib/docker/containers`
   directly (no Docker socket — that socket is root-equivalent). On a host where
   the Docker root differs, adjust the bind mount in the overlay.

## Troubleshooting

### PalatiumApiDown

1. `docker compose ps api` and `curl -s localhost:8000/health`.
2. If the API is up but the target is down: check the scrape token. In
   staging/production a missing/invalid JWT yields `401` on `/metrics`, which
   Prometheus reports as a failed scrape.
   `docker compose logs prometheus | grep -i '401\|forbidden'`.

### Grafana panels are empty

* Panel datasource UIDs must stay `palatium-prometheus` / `palatium-loki` — they
  are referenced by `datasources.yml` and by the dashboard JSON.
* `Grafana → Explore → Prometheus → up` confirms the datasource works at all.

### Alert fires as `unknown` severity

Every rule declares `labels.severity`. If Alertmanager shows `unknown`, the rule
file failed to load — check `Prometheus → /rules` and `promtool check rules`.
