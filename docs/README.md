# Документация Palatium AI

| Документ | Для кого |
|----------|----------|
| **[../START.md](../START.md)** | **Стартовая инструкция**: setup + `$PROFILE` + 3 режима + шпаргалка |
| **[max-pro-level-tz.md](max-pro-level-tz.md)** | Архитектурное ТЗ MAX PRO LEVEL 2026 (целевая картина; норматив — `.cursor/rules/`) |
| **[handbook.md](handbook.md)** | Полный путь: clone → env → Poetry/Docker → API → ops |
| **[docker.md](docker.md)** | Сборка и запуск в Docker (пошагово) |
| **[runbook.md](runbook.md)** | **Операторский runbook**: диагностика по симптому, фиксы, полный сброс |
| **[secrets.md](secrets.md)** | Секреты: локально, CI, Vault |
| **[ops-readiness.md](ops-readiness.md)** | Чеклист staging/prod после Weeks 0–8 remediation |
| **[agent-evals.md](agent-evals.md)** | Agent evals: PR baseline, cassette, nightly llm_judge |
| **[adr/README.md](adr/README.md)** | ADR: зачем, формат, шаблон и реестр архитектурных решений (правило `086`) |
| **[global-retention.md](global-retention.md)** | **Global retention**: env `RETENTION_*`, CLI, классы W0–W3, dry-run→execute, диагностика |
| **[adr/0002-global-retention-scheduler.md](adr/0002-global-retention-scheduler.md)** | ADR: global retention — out-of-band CronJob + узкая DB-роль |
| **[../.cursor/plans/global-retention.md](../.cursor/plans/global-retention.md)** | План Global Data Retention W0–W6: политики, scheduler, GDPR/152-ФЗ (актуально на 2026-10-05) |
| **[audit/latency-audit.md](audit/latency-audit.md)** | Аудит скорости ответа: карта `/intents/process`, узкие места, план P0–P2 (актуально на 2026-10-01) |
| **[embedded-assistant.md](embedded-assistant.md)** | Embeddable-виджет `<palatium-assistant>`: контракт событий, темизация, доставка, §9 — интеграционный пакет и чек-лист приёмки для команды СЭД |
| **[../deploy/observability/README.md](../deploy/observability/README.md)** | Observability-стек: Prometheus / Grafana / Loki / Alertmanager + SLO |
| **[../env/.env.example](../env/.env.example)** | Канон env + чеклист первого подъёма |

Витрина продукта (коротко, «нужно ли качать»): [../README.md](../README.md)
