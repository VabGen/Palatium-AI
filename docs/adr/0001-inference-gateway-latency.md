# 0001. Latency-оптимизации inference живут на corporate gateway

- **Статус:** accepted
- **Дата:** 2026-10-01
- **Правило-владелец:** 080 (performance), latency-audit P2.13–14

## Контекст

P50/P95 ответа зависят от двух слоёв: оркестрации в `palatium-ai` и serving
корпоративных LLM за LiteLLM. В репозитории нет SGLang/vLLM runtime — только
клиент к gateway (`deploy/litellm/config.yaml` + `LLM_PROVIDER=gateway`).

## Решение

1. **В репозитории (приложение):** топология графа, L1 response cache, SSE,
   hop budget, `latency-based-routing` в LiteLLM config, parallel workers.
2. **На corporate gateway (вне репо):** RadixAttention / continuous batching,
   speculative decoding (draft = nano), replica-пулы под один `model_name`.
3. Чеклист для ops — `docs/runbook.md` §5.2; аудит — `docs/audit/latency-audit.md` P2.13–14.

## Рассмотренные альтернативы

- **Вшить SGLang в compose приложения** — отвергнуто: corporate model gateway
  уже внешний; дублировать serving ломает единый auth/quota.
- **Speculative decoding в LiteLLM proxy без upstream** — отвергнуто: draft/target
  исполняет inference engine, не router.

## Последствия

- Метрики GPU util / TTFT gateway **не** появляются в Prometheus приложения
  без экспорта с gateway.
- Добавление второй реплики в `model_list` с тем же alias активирует
  `latency-based-routing` без правок Python.
- Speculative decoding и RadixAttention — только через замену/настройку
  upstream (SGLang/vLLM), не через код агентов.
