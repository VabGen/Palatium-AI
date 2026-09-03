# Reference — черновик RAG/памяти → финальная архитектура

Читай вместе со SKILL.md при рефакторинге `application/agents/`. Этот файл —
карта соответствия: что из исходного черновика «СОЗДАНИЕ УНИВЕРСАЛЬНОЙ
RAG-СИСТЕМЫ...» уже принято правилами 000–099, что заменено более поздним
решением, и какие решения зафиксированы в `docs/max-pro-level-tz.md` §17.

При противоречии этого файла и правил (000–099) — правила побеждают (055).
Черновик как единый .md-файл в репозитории **не хранится** — он вводит
параллельный источник истины по осям/реестру/стеку, что запрещено 050.

## 1. Реестр агентов: 7 → 12 ролей

Черновик описывает 7 агентов (Planner, Router, Retriever/Executor, Graph
Traversal Agent, Critic, Memory Agent, Learning Agent). Финальный реестр —
таблица в 000 (единственный источник). Соответствие:

| Черновик | Статус в 000 | Что делать при рефакторинге |
|---|---|---|
| Planner | `merged` → supervisor | Отдельного агента не создавать; DAG/декомпозиция — обязанность supervisor |
| Router | НЕ агент | Семантическая маршрутизация — логика/узел внутри supervisor или графа, не класс `RouterAgent` (000) |
| Retriever/Executor | → `researcher` (+ `text_ingestor`, `coder`, `analyst`) | Разделены по ответственности: researcher — гибридный поиск/MCP, text_ingestor — чанкинг при ингесте (`planned`), coder/analyst — `deferred`, создаются по мере необходимости, не заранее |
| Graph Traversal Agent | нет отдельного агента | Multi-hop и комьюнити-суммаризация — через MCP-инструмент `graph_query` (070), вызывается researcher'ом, а не отдельным агентом |
| Critic | exists | Как в черновике; quality gate — не RAGAS напрямую, см. §3 |
| Memory Agent | → `memory_keeper` | exists |
| Learning Agent | **deferred** (вне реестра) | Не добавлять; см. `docs/max-pro-level-tz.md` §2, §17.1 |

`Router — НЕ агент` — из 000 дословно; не заводить `RouterAgent` даже как
тонкую обёртку над семантическим роутером.

## 2. Контракты ввода/вывода: Dict[str, Any] → pydantic

Черновик даёт `AgentInput`/`AgentOutput`/`AgentConfig` как обычные pydantic
`BaseModel` со свободными `Dict[str, Any]`-полями (`context`, `artifacts`,
`tools: List[Any]`, `config: Dict[str, Any]`). Это преодолено 010/030:

- `AgentInput.context` — `dict[str, str]` (строго строковые значения; rich-
  объекты — через context-ключи, собираемые `ContextBuilder`, не произвольные
  поля модели). См. 030.
- `AgentConfig` — frozen pydantic, конкретные типизированные поля (`role`,
  `model_tier`, `temperature`, `allowed_tools: tuple[str, ...]`, ...), не
  `Dict[str, Any]`. См. 030.
- `BaseAgent.__init__(self, harness, config)` из черновика верен по духу,
  но `config: Dict[str, Any]` → `config: AgentConfig`.
- `verify()` в черновике сравнивает `confidence >= config.get('min_confidence', 0.7)`
  — в финальном контракте это `confidence_threshold` из `AgentConfig`
  (Field, не `.get()` со свободным дефолтом) и НЕ единственная проверка:
  провал `verify()` понижает статус до `partial` + эскалация (030.7),
  а не просто выставляет `requires_review=True`.
- `AgentOutput.response: str` в черновике → в финальном контракте
  `output: BaseModel`, конкретный подтип объявляет сам агент (010, 030) —
  структурированный вывод, не голая строка.

## 3. Critic / RAGAS vs LLM-as-a-Judge

Черновик предлагает метрики RAGAS (Faithfulness, Answer Relevancy, Context
Relevancy). Финальный контракт (040) — LLM-as-a-Judge с порогами
`accuracy < 6/10` / `safety < 8/10`, судья — модель другого провайдера,
low-risk стратегии проходят без судьи (CriticPolicy, 055).

Это **не исключает** идею RAGAS — Faithfulness/Relevancy можно использовать
как критерии внутри промпта судьи. Но заводить отдельную RAGAS-метрику/
библиотеку мимо контракта 040 — самостоятельное архитектурное решение,
которое нужно явно обсудить, а не внедрять по умолчанию при рефакторинге.

## 4. Технологический стек — что уже решено, что отклонено

| Черновик | Финальное решение | Источник |
|---|---|---|
| LangMem + Cognee | Принято, уже в стеке | 099 |
| Qdrant / pgvector (альтернативы) | pgvector — единственный векторный слой (`knowledge`/`memory` схемы) | 060, 099 |
| BM25 через ParadeDB (`pg_search`) | **Отклонено.** Гибридный поиск = pgvector (cosine) + Postgres FTS (`tsvector`/`ts_rank_cd`). Называть это «BM25» — ошибка; сторонние расширения — только после отдельного решения в 000 | 060.6 |
| Reasoning LLM (o1/o3-mini, DeepSeek-R1) для Planner/Critic | Конкретная модель — не хардкод в правилах; задаётся `model_tier` (`frontier`/`standard`/`fast`) в `AgentConfig` + LiteLLM fallback-цепочка ≥2 провайдера | 030, 020 |
| Dynamic Semantic Chunking / Late Chunking / parent-child | Реализационная деталь `text_ingestor` (статус `planned`) — не противоречит правилам, реализуется при создании агента | 000 |
| Anthropic Contextual Retrieval (context-prefix перед embed) | Согласуется с каноном (раздел B, `anthropic-canon.md` в `max-pro-review`); реализуется в пайплайне `text_ingestor` | канон B |
| RRF + Cross-Encoder rerank | Реализационная деталь гибридного поиска, не противоречит 060 | — |
| CAG / prompt-кэширование частых запросов | Не описано в правилах явно. Если реализуется — это часть `RouteStrategy` (домен `domain/policies/`, 055), не отдельный `if` в Router/Supervisor и не отдельный агент | 055 |
| xMemory (decouple-before-aggregate) | **deferred** — рекомендация, не v1 | см. `docs/max-pro-level-tz.md` §6.4, §17.2 |
| Learning Agent + периодический fine-tuning | **deferred**, вне реестра | `docs/max-pro-level-tz.md` §2, §17.1 |

## 5. Зафиксированные решения (ранее «открытые вопросы»)

Решения приняты в `docs/max-pro-level-tz.md` §17. Менять — только явным
решением пользователя **и** правкой соответствующего правила (000/055/060/040),
не тихое расхождение между ТЗ и кодом.

| # | Вопрос | Решение |
|---|---|---|
| 1 | Learning Agent | **deferred** — не в реестре; PII-риск обучающих данных (§6.5) |
| 2 | xMemory consolidation | **deferred** — текущая consolidation достаточна для старта (§6.4) |
| 3 | RAGAS-критерии | Не отдельный пайплайн; допустимы в промпте LLM-as-a-Judge (§12) |
| 4 | CAG/prompt-кэширование | Не через Router; при необходимости — `RouteStrategy` в `domain/policies/types.py` (§5) |

До явного пересмотра эти пункты не реализуются «по умолчанию» ни в одной волне
`max-pro-review` / `agent-refactoring`.

## 6. Структура пакета и план волн

Черновик предлагает свою структуру `application/agents/{base.py, harness.py,
registry.py, core/, orchestrator/, agents/}` и 9-этапный план на 20–22
недели. Используй вместо неё:

- **Структуру каталогов** — таблицу «Назначение каталогов» в 000
  (`domain/agents`, `domain/ports`, `application/agents/<name>/`,
  `application/orchestration/`, `application/tools/`, `infrastructure/**`) —
  она детальнее и уже согласована со слоевой моделью (импорты только вниз).
- **Порядок и группировку работ** — `waves.md` в `max-pro-review`
  (Wave 1 `domain/` → Wave 2 `application/` → Wave 3 `core/` → Wave 4
  `infrastructure/` → ...), а не 9 этапов черновика. Соответствие:

| Этап черновика | Волна |
|---|---|
| 1. Фундамент (схемы БД) | Wave 1 (`domain/memory`) + Wave 4 (`infrastructure/database`) |
| 2. Поисковый слой | Wave 4 (`infrastructure/memory`, `infrastructure/llm`) |
| 3. Слой памяти (ядро) | Wave 1 (`domain/memory`) + `memory_keeper` в Wave 2 |
| 4. Графовый слой | Wave 4 (`infrastructure/mcp`, `graph_query`) |
| 5. Многоагентная оркестрация | Wave 1 (`domain/agents`) + Wave 2 (`application/orchestration`) |
| 6. MCP-сервер | Wave 2 (`application/tools`) + Wave 7 (`mcp_servers/`) |
| 7. Контекстуальное обогащение | часть Wave 1/2 при реализации `text_ingestor` |
| 8. Наблюдаемость и безопасность | Wave 3 (`core/observability`) + сквозные проверки во всех волнах (020/040 — `alwaysApply: true`) |
| 9. Тестирование и оптимизация | Wave 8 (`tests/`) |

Волны не параллелятся (`max-pro-review/waves.md`); длительность в неделях
из черновика — ориентир, не обязательство.

## 7. Что из черновика переносится как есть

Без конфликтов, реализуется по мере создания соответствующих агентов/слоёв:
Reciprocal Rank Fusion после параллельного pgvector+FTS поиска;
контекстуальное обогащение чанков перед эмбеддингом; иерархия памяти
short/medium/long-term (уже описана в 060 в тех же терминах); JIT + progressive
disclosure в `ContextBuilder` (065); идея `SkillLoader`, подгружающего
`reference.md` по требованию, — уже реализована как паттерн
`.cursor/skills/*` в этом репозитории.

## 8. Baseline и полное ТЗ

- **Описательное ТЗ:** `docs/max-pro-level-tz.md` — целевая картина, контракты
  (§3.1), структура каталогов (§3.2), зафиксированные решения (§17).
- **Baseline кода:** `docs/max-pro-level-tz.md` §19 — обновлять после волн FIX.
- **Порядок внедрения:** `.cursor/skills/max-pro-review/waves.md`.
