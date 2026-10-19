# Formatter: schema-first contract (canary rollout)

**Статус:** Фаза 1–2 в коде, Фаза 3 (canary) включена на staging.
**Дата:** 2026-10-16.

Два контракта генерации `ContentDocument`, выбираемые `FORMATTER_MODE`:

| Контракт | Как получается документ | Путь удаления |
|---|---|---|
| `legacy` | GFM Markdown → `markdown_parser.py` + repair-loop | Фаза 4 |
| `schema_first` | провайдеру отдаётся `response_format=json_schema` от `ContentDocument` | целевой |

`schema_first` не парсит Markdown регулярками: модель заполняет типизированный
`schema` (`strict: true`), результат валидируется тем же pydantic-классом.

## Ключи конфигурации (two-key, как `ADAPTIVE_GROUNDING_*`)

| Ключ | Смысл |
|---|---|
| `FORMATTER_MODE` | `legacy` (kill switch) или `schema_first` (целевой контракт) |
| `FORMATTER_ROLLOUT_PCT` | покрытие `schema_first`: `0` off, `1..99` sticky-canary, `100` полный cutover |

`FORMATTER_MODE=schema_first` **сам по себе не переключает всех**: при `PCT=0` работает
legacy и пишется warning `formatter.rollout.zero_coverage`. Так одиночная правка
`MODE` не становится footgun'ом (та же логика, что `warn_if_enabled_but_zero_rollout`).

Резолв — чистая функция `resolve_formatter_mode` (`core/observability/formatter_rollout.py`),
когорта sticky по `hash8(user_id) % 100`. Один процесс обслуживает обе когорты
детерминированно: rolling update не переключает контракт пользователя на середине диалога.

## Canary на staging

`env/.env.staging(.example)`: `FORMATTER_MODE=schema_first`, `FORMATTER_ROLLOUT_PCT=5`.
Рампа без деплоя: `5 → 25 → 50 → 100`.

**Rollback — один ключ:** `FORMATTER_ROLLOUT_PCT=0` (оставить `MODE=schema_first`, чтобы
вернуть рампу одной правкой). Полный откат: `FORMATTER_MODE=legacy`.

## Метрики сравнения (Прометей, единый реестр 040)

Исходы пишутся в `node_name` канонической `palatium_agent_request_duration_seconds`
(`agent_type="formatter"`):

- `formatter:legacy` / `formatter:schema_first` — latency по когорте (mode-split);
- `schema_first:success`, `schema_first:unsupported` (провайдер отверг),
  `schema_first:invalid_json` (нарушение схемы), `schema_first:empty_blocks`;
- `emit:llm`, `emit:fallback_after_parse_errors`, `emit:fallback_deterministic`.

Доля нарушений схемы (`schema_first:invalid_json`) — главный сигнал: ожидается ≈ 0.

```promql
# Доля schema_first, доехавших до fallback на legacy
sum(rate(palatium_agent_request_duration_seconds_count{agent_type="formatter",node_name=~"schema_first:(unsupported|invalid_json|empty_blocks)"}[1h]))
/
sum(rate(palatium_agent_request_duration_seconds_count{agent_type="formatter",node_name=~"schema_first:.*"}[1h]))

# p95 latency schema_first против legacy
histogram_quantile(0.95, sum by (le) (rate(palatium_agent_request_duration_seconds_bucket{agent_type="formatter",node_name="formatter:schema_first"}[1h])))
/
histogram_quantile(0.95, sum by (le) (rate(palatium_agent_request_duration_seconds_bucket{agent_type="formatter",node_name="formatter:legacy"}[1h])))
```

## Триггеры отката

| Триггер | Действие |
|---|---|
| `schema_first:(unsupported\|invalid_json)` / schema_first > 0.5% | `PCT=0`, разобрать провайдера/схему |
| p95(schema_first) / p95(legacy) > 1.2 | пауза рампы |
| format-регрессии (иконки, списки, формальность) | `PCT=0` |

Fallback спроектирован как degraded-graceful: при отказе провайдера, невалидном JSON или
пустом `blocks` на непустом ответе вызов переоткрывает legacy-путь, а не теряет ответ.

## Границы

- Удаление legacy (`markdown_parser.py`, `icon_sanitizer.py`, repair-слой, Markdown-промпты) —
  **Фаза 4**, после 99%+ `schema_first`. До этого legacy остаётся fallback'ом и не расширяется.
- `strict: true` держится на нормализации схемы в `domain/llm/structured_output.py`
  (`strict_json_schema`): без неё провайдер игнорирует дефолтные поля (например, `blocks`).
