# Loki canaries (Adaptive Grounding + secrets)

## Token leak (critical → security channel)

```logql
count_over_time(
  {app="palatium-ai"} |= "sk-"
  |~ "sk-[A-Za-z0-9]{20,}" [5m]
) > 0
```

Purpose: catch a secret pattern the observability redactor does not yet know.
Companion to `scripts/lint_observability.py` (static) and `core/observability/redaction.py` (runtime).

## Enabled but zero rollout (warning)

```logql
count_over_time(
  {app="palatium-ai"} |= "enabled_but_zero_rollout" [10m]
) > 0
```

Fires when `ADAPTIVE_GROUNDING_ENABLED=true` and `ADAPTIVE_GROUNDING_ROLLOUT_PCT=0`
(startup warning from `setup_observability`). Expected on rollback/`PCT=0`; unexpected
after intentional `PCT>0` flip → config not applied or pods still on old env.

Grafana panel **1.4** on `palatium-adaptive-grounding` dashboard.

## Judge failures (warning)

```logql
count_over_time(
  {app="palatium-ai"} |= "grounding.judge_failed" [5m]
) > 0
```

Prefer Prometheus `palatium_grounding_judge_failed_total` when available; LogQL is the fallback.
