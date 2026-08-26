# Секреты palatium-ai

Цель: **в git только плейсхолдеры**, реальные ключи — вне репозитория.

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  Developer  │     │  CI (GitHub)     │     │  Runtime (prod)     │
│  env/.env*  │     │  Actions Secrets │     │  Vault → env vars   │
│  (gitignore)│     │  → job env       │     │  или K8s Secret     │
└─────────────┘     └──────────────────┘     └─────────────────────┘
        │                     │                         │
        └──────────► pydantic Settings ◄────────────────┘
                     (ENV_FILE + process env)
```

Приложение читает `ENV_FILE` и **process env поверх файла** (Vault inject).  
**Правило prod:** в git/файле — каркас без секретов; секреты из Vault/CI.

Полный справочник переменных с чеклистом админа: **[`env/.env.example`](../env/.env.example)**.

---

## 1. Файлы в `env/`

| Файл | В git? | Назначение |
|------|--------|------------|
| `.env.example` | да | канон всех ключей + легенда MUST-SET/SECRET/PROD |
| `.env.local.example` | да | Ollama local |
| `.env.cloud.example` | да | OpenAI cloud |
| `.env.staging.example` | да | каркас staging |
| `.env.prod.example` | да | каркас production |
| `.env`, `.env.dev`, `.env.staging`, `.env.prod` | **нет** (gitignore) | рабочие копии с секретами |

```powershell
copy env\.env.example env\.env
# или готовый профиль:
copy env\.env.local.example env\.env
copy env\.env.staging.example env\.env.staging
```

### Auth

| Переменная | Dev | Staging/Prod |
|------------|-----|--------------|
| `AUTH_ENABLED` | `true` | `true` |
| `JWT_ALGORITHM` | `HS256` | `RS256` |
| `JWT_SECRET` | локальный секрет (не в git) | пусто |
| `HITL_SIGNING_SECRET` | опционально (=`JWT_SECRET`) | **обязателен** при RS*/ES* |
| `JWKS_URL` | пусто | URL IdP JWKS |
| `CORS_ORIGINS` | `http://127.0.0.1:8000,...` | явный allow-list UI origin |
| `API_RATE_LIMIT` | лимит `/classify`+`/process` на principal | то же |
| `TURN_COST_BUDGET_USD` / `DAILY_COST_BUDGET_USD` | `0` OK для DIY | **>0** |
| `LLM_FALLBACK_PROVIDERS` | рекомендуется | ≥1 fallback |

Локальный UI: `POST /api/auth/dev-token` (**только** `ENVIRONMENT=development`).

**Не устанавливайте пакет `jwt`** — только **`PyJWT`**.

```powershell
# обычный запуск
$env:ENV_FILE = "env/.env.dev"
poetry run python -m palatium_ai.main
```

---

## 2. CI secrets (ближайший шаг)

Список секретов в GitHub → **Settings → Secrets and variables → Actions**:

| Secret              | Куда мапится                   |
|------------------------------------------------------|
| `POSTGRES_PASSWORD` | `POSTGRES_PASSWORD`            |
| `OLLAMA_API_KEY`    | `OLLAMA_API_KEY`               |
| `LANGCHAIN_API_KEY` | `LANGCHAIN_API_KEY`            |
| `REDIS_PASSWORD`    | `REDIS_PASSWORD` (если есть)   |
| `JWKS_URL`          | `JWKS_URL` (если не публичный) |

В workflow секреты **не печатают** и не пишут в артефакты:

```yaml
env:
  ENV_FILE: env/.env.staging
  POSTGRES_PASSWORD: ${{ secrets.POSTGRES_PASSWORD }}
  OLLAMA_API_KEY: ${{ secrets.OLLAMA_API_KEY }}
  LANGCHAIN_API_KEY: ${{ secrets.LANGCHAIN_API_KEY }}
```

Скелет: [`.github/workflows/deploy-staging.example.yml`](../.github/workflows/deploy-staging.example.yml).

То же для cron-скриптов retention из README — вместо комментария «передать через secrets» явная `env:`-секция.

---

## 3. Docker Compose (промежуточный prod/staging)

Скелет: [`deploy/compose.secrets.example.yml`](../deploy/compose.secrets.example.yml).

Идея:
- `env/.env.prod` монтируется как **не-секретный** каркас (хосты, порты, имена моделей).
- Пароли/ключи — через `environment:` из host env или Docker secrets.

```powershell
$env:POSTGRES_PASSWORD = "..."
$env:OLLAMA_API_KEY = "..."
docker compose -f deploy/compose.secrets.example.yml up
```

---

## 4. Vault (целевой L0, когда появится infra)

Пути (пример):

```
secret/palatium/staging/postgres   → password
secret/palatium/staging/ollama     → api_key
secret/palatium/prod/postgres      → password
secret/palatium/prod/ollama        → api_key
```

Варианты инъекции:

1. **Sidecar / agent** на ноде пишет env перед стартом процесса  
2. **External Secrets Operator** (K8s): Vault → `Secret` → pod env  
3. **CI job** читает Vault по short-lived token и передаёт в deploy (хуже, чем ESO)

Скрипт-заглушка: [`scripts/load-secrets-from-vault.example.sh`](../scripts/load-secrets-from-vault.example.sh).

Пока Vault нет — используйте CI secrets + Compose; путь к Vault оставьте совместимым (`POSTGRES_PASSWORD`, `OLLAMA_API_KEY` и т.д. — те же имена, что в `.env`).

---

## 5. Чеклист перед merge в main

- [ ] В diff нет реальных `OLLAMA_API_KEY` / паролей БД  
- [ ] `secret-scan` hook / CI не красный  
- [ ] Staging/prod запускаются с плейсхолдерами в файле + секретами снаружи  
- [ ] Локальный `.env*` не коммитится (см. `.gitignore`)

---

## Минимальный порядок внедрения

1. **Сейчас** — локальные `env/.env*` + gitignore (уже есть).  
2. **CI** — завести GitHub Secrets и скопировать `deploy-staging.example.yml` → `deploy-staging.yml`.  
3. **Compose** — когда появится единый docker-стек приложения.  
4. **Vault** — когда будет общий infra-контур IBA / K8s.

---

## Docker-образ приложения

Multi-stage targets (`Dockerfile`):

| Target | Назначение |
|--------|------------|
| `runtime` (default) | Prod API: только `.venv` + app, **без** Poetry/gcc |
| `test` | CI: `pytest` |
| `devtools` | Shell + Poetry внутри контейнера (не для prod) |

```bash
docker build -t palatium-ai:local .
docker build --target test -t palatium-ai:test .
docker run --rm -p 8000:8000 --env-file env/.env palatium-ai:local
docker run --rm -e RUN_MIGRATIONS=1 --env-file env/.env palatium-ai:local

docker compose -f deploy/compose.secrets.example.yml up --build
```

Poetry намеренно отсутствует в `runtime`: меньше CVE-поверхность, меньше образ,
immutable runtime. Сборка зависимостей — только в stage `builder` по `poetry.lock`.

Образ **не содержит** `env/.env*` с секретами (см. `.dockerignore`).

**Полная пошаговая инструкция:** [`docs/docker.md`](docker.md).
