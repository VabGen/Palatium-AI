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
│   └── dashboards/
│       ├── palatium-overview.json
│       └── palatium-adaptive-grounding.json
├── loki/loki-config.yml
└── promtail/promtail-config.yml
```

## Run

This overlay is part of `make up-full` and `make obs-up` (since 2026-11-18). The two
files must be passed together — `--profile observability` on the base file alone starts
only Langfuse v3, because Prometheus/Grafana/Loki/Alertmanager are defined *here*.

```bash
# 1. Grafana refuses to start without an admin password (no default password in git).
#    Add these to env/.env (gitignored):
#      GRAFANA_ADMIN_PASSWORD=<local-only-password>
#
# 2. Start the full stack + observability overlay:
make up-full
# equivalent, manual:
docker compose --env-file env/.env \
  -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  --profile observability up -d --build
```

| Service | URL | Notes |
|---|---|---|
| Prometheus | http://localhost:9090 | targets: `/targets`, rules: `/rules` |
| Alertmanager | http://localhost:9093 | default receiver is a no-op — see below |
| Grafana | http://localhost:3001 | *Overview* + *Adaptive Grounding*; 3000 belongs to Langfuse |
| Loki | http://localhost:3100 | query via Grafana Explore |
| Promtail | — | opt-in: `--profile logs-shipper`, Linux hosts only (see below) |

Everything binds to `127.0.0.1` only (020: nothing exposed on the perimeter).

### Memory budget

The five containers declare `mem_limit` (prometheus 256 + alertmanager 96 + grafana 256 +
loki 256 = 864 MiB, promtail 96 MiB when enabled) and that sum is part of the VM budget
asserted by `tests/unit/test_container_hardening.py`. Unbounded, a runaway Grafana/Loki is
reaped by the *VM-wide* OOM killer, which picks the largest RSS — postgres. `make up-full`
therefore checks the ceilings against `docker info` before starting (`memory=13GB` in
`%USERPROFILE%\.wslconfig` on a 16 GB dev host).

### Promtail is opt-in, and host-specific

Promtail reads the Docker daemon's container-log directory
(`/var/lib/docker/containers`). On Docker Desktop for Windows that path lives inside the
WSL VM, not on the Windows host: bind-mounted from the host it is an empty directory, so
the container is healthy and ships nothing while Loki looks like it is collecting logs.
A profile makes that failure honest — nothing starts — instead of silent. Run it
explicitly on a Linux host where the path exists:

```bash
docker compose --env-file env/.env -f docker-compose.yml \
  -f deploy/observability/compose.observability.yml \
  --profile logs-shipper up -d promtail
```

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
uv run pytest tests/unit/test_observability_assets.py -q
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
   directly (no Docker socket — that socket is root-equivalent) and is therefore opt-in
   behind `--profile logs-shipper`. On Docker Desktop for Windows that path sits inside
   the WSL VM, so the mount is empty and only the profile keeps that failure visible;
   on a host where the Docker root differs, adjust the bind mount.

## Troubleshooting

### `mkdirat etc/prometheus/prometheus.yml: file exists` / Loki `is a directory`

Compose resolves bind paths from the **repo root** (first `-f`), not from
`deploy/observability/`. Old overlay paths like `./prometheus/prometheus.yml`
created empty host *directories* at the repo root; Docker then failed to mount
them over config *files* in the image.

1. Stop obs containers and remove the accidental dirs (not under `deploy/`):

```powershell
docker compose --env-file env/.env `
  -f docker-compose.yml `
  -f deploy/observability/compose.observability.yml `
  stop prometheus alertmanager grafana loki promtail
docker compose --env-file env/.env `
  -f docker-compose.yml `
  -f deploy/observability/compose.observability.yml `
  rm -f prometheus alertmanager grafana loki promtail

Remove-Item -Recurse -Force prometheus, alertmanager, grafana, loki, promtail -ErrorAction SilentlyContinue
```

2. Confirm configs are real files: `deploy/observability/prometheus/prometheus.yml`
   (and peers) — Mode should be **file**, not directory.

3. Bring the overlay back up (paths are already fixed to `./deploy/observability/...`).

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
