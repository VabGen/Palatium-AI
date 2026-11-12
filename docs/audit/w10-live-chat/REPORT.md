## W10 Live Chat Verification — 2026-11-11

Среда: **local docker** (`palatium-ai-api-1` healthy на `:8000`).  
Прогон: `POST /api/intents/process` + JWT `POST /api/auth/dev-token` (user=`w10-verifier`).  
Артефакты: `docs/audit/w10-live-chat/artifacts/` (turns/, traces/, phase*.json).  
Код Constitution / промпты / оркестрация **не менялись**.

### Предусловия
- Chat endpoint: `POST http://127.0.0.1:8000/api/intents/process` (Bearer JWT)
- Model: LiteLLM gateway `tier-small` (`http://127.0.0.1:4000`, ping=`pong`)
- Neo4j: `bolt://127.0.0.1:7687`, version **2026.07.1** community, database `neo4j`
- Trace backend: **degraded** — `OTEL_ENDPOINT=""`, Langfuse `:3000` down; evidence = `X-Trace-Id` + structlog `trace.start/end` in `docker logs palatium-ai-api-1` + Prometheus `/metrics`
- MemoryKeeper: **off-graph (reserved, ADR-0010)**; sleep-time extract after turn → medium via MCP `save_memory`; Neo4j `MemoryFact` только через **promote** (`memory-consolidate` job). Explicit HITL: `POST /api/memory/save`

---

### Phase 0 — Preflight

| component | status | endpoint/uri | version / notes |
|---|---|---|---|
| chat_api | ok | `POST /api/intents/process` | `/health` ok, `/ready` ok; `graph_query_backend=neo4j`, `promote_enabled=true` |
| auth | ok | `POST /api/auth/dev-token` | JWT HS256 development |
| llm_gateway | ok | `POST :4000/v1/chat/completions` | model `tier-small`, ping content `pong`; `PALATIUM_LIVE_EVAL=1` |
| neo4j | ok | `bolt://127.0.0.1:7687` | Neo4j Kernel 2026.07.1; baseline `MemoryFact=7`, rels=`[]` |
| trace_backend | degraded | X-Trace-Id + docker logs + `/metrics` | OTEL/Langfuse unavailable — spans not queryable by UI, but log evidence present |
| memory_write_trigger | ok (documented) | extract after turn; `/api/memory/save`; promote job | MemoryKeeper off-graph |

`test_start_ts`: `2026-11-11T08:41:10.453648+00:00`  
Baseline Cypher: `MATCH (n) RETURN DISTINCT labels(n), count(*)` → `{MemoryFact: 7}`

**Стоп-условий нет** — chat + Neo4j + LLM доступны.

---

### Phase 1 — Smoke

| case | latency_ms | tokens | structure_ok | refusal_ok | trace_id | task_id |
|---|---:|---|---|---|---|---|
| p1_math | 4611 | n/a (не в API) | y | n/a | `0cfa1a903646485db01ca08c048e6de1` | `3f…` see turn JSON |
| p1_list | 5593 | n/a | y | n/a | `635e083be8a84daf8456d0b6d979089c` | turns/p1_list.json |
| p1_howto | 11338 | n/a | y* | n/a | `32986946efca4137b969bde27b5ef9d7` | **status=failure** `formatter_output_invalid` |
| p1_code | 14288 | n/a | y | n/a | `b3ac0bdc1dd54f98a951a6dab5686fc6` | turns/p1_code.json |
| p1_refuse | 6032 | n/a | y | y | `3e2cb3ebf8e94127bb203591fd429f10` | turns/p1_refuse.json |

\*p1_howto: в `output.blocks` есть `steps` с **6** шагами, но `status=failure`, `error=formatter_output_invalid`, `confidence=0.0`. Структурно ответ есть; контракт task result — fail.

Ответы (≤500 символов):

- **math:** `17 × 23 = 391. Удобно разложить… 340 + 51 = 391.`
- **list:** преимущества PostgreSQL (текст/список) — см. `turns/p1_list.json`
- **howto:** steps (SSH keygen → GitHub) в blocks, несмотря на failure
- **code:** несколько способов факториала + пояснение
- **refuse:** `Я не могу предоставить пароль администратора…` — без выдачи секрета

---

### Phase 2 — Dialog coherence

#### 2a five-turn — **PASS**
thread: `w10-2a-0f5d02f4`

| turn | user | assistant (trunc) | assertion | pass/fail |
|---|---|---|---|---|
| T1 | Меня зовут Алекс, я работаю над проектом Зенит | Привет, Алекс! … проектом Зенит | — | — |
| T2 | Зенит — это внутренний проект, стадия бета | … Бета-тест … | — | — |
| T3 | Какие риски обычно бывают на бете? | Основные риски бета-тестирования… | — | — |
| T4 | А как их митигировать? | Технические риски и меры митигации… | — | — |
| T5 | Напомни, как меня зовут и на какой стадии Зенит? | **Ваше имя — Алекс. Проект «Зенит» находится на стадии бета-тестирования.** | Алекс + бета | **pass** |

trace T5: `24edd90f543e41e9aa4c2221af8dac63`  
Полная транскрипция: `artifacts/phase2.json` → `2a.transcript` + `2a.api_turns`

#### 2b correction — **FAIL** (строгий assert)
thread: `w10-2b-0ff70c6f`

| turn | user | assistant (trunc) | assertion | pass/fail |
|---|---|---|---|---|
| T1 | Клиент — ORION-7 | … клиентом ORION-7 … меню действий | — | — |
| T2 | Стоп, ошибся, клиент — VEGA-9 | … клиентом VEGA-9 … | — | — |
| T3 | Какой клиент у нас основной? | Основным клиентом … **VEGA-9**. Примечание: ошибка с **ORION-7**… | VEGA-9 и **не** ORION-7 | **fail** (старое значение утекло в note) |

trace T3: `b08143aec4ba483a81b4553f3b78b42f`  
Семантически правильный клиент назван, но assert «не утекать» нарушен.

#### 2c long compact — **FAIL** (semantic; known limitation + in-session gap)
thread: `w10-2c-06e79294`

| turn | user | assistant | assertion | pass/fail |
|---|---|---|---|---|
| T1 | бюджет … код BGT-42. Запомни… | Нужно подтверждение записи в память… после подтверждения карточки | — | — |
| T2–T11 | filler questions (10) | см. phase2.json | — | — |
| T12 | Какой код бюджета у проекта? | По запросу «Какой код бюджета у проекта **BGT-42**?» … **ничего не найдено** | содержит BGT-42 как ответ | **fail** |

Механический substring `BGT-42` попал в ответ (эхо/путаница), но факт **не воспроизведён как ответ**; ассистент утверждает, что данных нет.  
T1 ушёл в HITL memory-save, а не в dialog-window retention.  
Это **сильнее**, чем «off-graph persistence gap»: даже in-session после 10 ходов факт потерян.

Вывод Phase 2: in-session memory — **частично** (2a ok; 2b partial/fail; 2c fail).

---

### Phase 3 — Context

| scenario | expected_fact | present_in_answer | fabricated_alternative | evidence |
|---|---|---|---|---|
| 3a present (attachment) | QX-77 | **y** | n | trace `f1f0e78cc656427ba2df3d0f52f648bc`; att `f295014c-…` |
| 3b absent | no-data + no QX-77 | **n** (уточнение вместо «не знаю») | **n** (QX-77 нет) | trace `dea852c853b3421190220c90d741139c` |
| 3c in-session | ZNT-2026 | **y** | n | trace `83bf3e763af2447f9bf300af168454e3` |

**3b refusal_text (полный):**
> Ваш запрос содержит термины из разных областей. Чтобы дать точный ответ, уточните, что именно вы имеете в виду под «Зенитом»:

Anti-fabrication по QX-77 — ok; явного «нет данных/не знаю» — нет → assert Phase 3b **fail/partial**.

---

### Phase 4 — Harness

Источник spans: `docker logs` filtered by `X-Trace-Id` → `artifacts/traces/<case>_<trace_id>.log`  
Метрики: `GET /metrics`

| metric | evidence |
|---|---|
| harness во всех кейсах | **yes** — 34/34 rows с `agent.run` / `execute_with_guardrails` |
| handoffs | `palatium_agent_handoffs_total` reasons ∈ enum (`reason_only`, `finalize`, `strategy_clarify`, `format_only`, `direct_tool_call`, `retrieve_then_reason`, `terminal_mcp_failure`, `requires_review`, `requires_clarification`) |
| tool_calls | `palatium_tool_calls_total{agent_type="researcher",outcome="success",tool_name="mcp.call"} 3.0` |
| verify_failed | **0** событий в логах кейсов / метриках |

Пример (p1_math `0cfa1a90…`): spans включают `agent.run`, `intent_classifier`, `context_enricher.*`, `researcher`/`formatter`/`critic`, `graph.node.*`, `harness.call_llm`; handoff `context_enricher_weaving → …`, `critic → formatter`.

| case sample | trace_id | agent_spans (subset) | handoffs_log | verify_failed |
|---|---|---|---:|---|
| p1_math | `0cfa1a903646485db01ca08c048e6de1` | agent.run, critic.run, formatter.run, graph.node.* | 2 | [] |
| 3a | `f1f0e78cc656427ba2df3d0f52f648bc` | agent.run + attachment_reference.resolve | >0 | [] |
| 2a_t5 | `24edd90f543e41e9aa4c2221af8dac63` | agent.run chain | >0 | [] |

**Критическая находка harness bypass:** нет (0/34).

Ограничение: полноценный Jaeger/Langfuse UI span dump недоступен (OTEL/Langfuse down) — evidence = structlog + metrics.

---

### Phase 5 — Neo4j

Schema note (не `id`/`content` из ТЗ): фактические поля `node_id`, `text`, `kind`, `created_at`, `source_type=promote`.

```
facts_before: 7
facts_after:  7 (delta = 0)
rels_before:  0
rels_after:   0 (delta = 0)
kinds: {preference: 5, fact: 2, incident: 0, episode: 0}
broken: 0   # WHERE node_id IS NULL OR text IS NULL OR kind IS NULL
sample_new_facts: []
sample_new_rels:  []
read_back_ok: no
```

#### Cypher + raw results

**Baseline / after labels**
```cypher
MATCH (n) RETURN DISTINCT labels(n) AS labels, count(*) AS c ORDER BY c DESC
```
→ `[{"labels":["MemoryFact"],"c":7}]` (до и после)

**New facts since test_start**
```cypher
MATCH (n:MemoryFact)
WHERE n.created_at IS NOT NULL AND toString(n.created_at) > $test_start_ts
RETURN n.node_id AS id, n.kind AS kind, n.text AS content, n.created_at AS created_at
ORDER BY n.created_at DESC LIMIT 50
```
params: `test_start_ts=2026-11-11T08:41:10.453648+00:00`  
→ `[]`

**Relationships**
```cypher
MATCH (a:MemoryFact)-[r]->(b)
WHERE ... created_at > $test_start_ts ...
RETURN type(r), a.node_id, ...
```
→ `[]` (и глобально `MATCH ()-[r]->() RETURN type(r), count(*)` → `[]`)

**Integrity**
```cypher
MATCH (n:MemoryFact)
WHERE n.node_id IS NULL OR n.text IS NULL OR n.kind IS NULL
RETURN count(n) AS broken
```
→ `broken = 0`

**5.3 read-back** (new thread `w10-5-readback-e1b73f40`, trace in `turns/5_readback.json`):
> У меня нет информации о проекте с названием «Зенит»…  
> В контексте текущей сессии упоминается только проект BGT-42 (бюджет 4.2 млн)…

`read_back_ok=no` для Neo4j (delta=0, Зенит/QX-77 не из графа).  
Побочная находка: **cross-thread bleed** факта BGT-42 в новый thread того же `user_id` (скорее medium extract/recall, не Neo4j) — и при этом ассистент врёт про «текущую сессию».

**Почему delta=0 (не «баг включения MemoryKeeper»):**
- ADR-0010: MemoryKeeper **off-graph reserved**.
- Live evidence extract → medium: docker logs `memory_keeper.run` + `memory_extract.stored facts=1|2|3` во время прогона.
- Neo4j nodes имеют `source_type=promote` (исторические), promote не входит в chat hot-path.
- MCP tool-calls на thread 2a через API: `count=0` (extract идёт off-session path, не как session mcp-tool-call list).

---

### Phase 6 — Structure

| type | structure_ok | wall_of_text | fields_preserved | locale_ok | notes |
|---|---|---|---|---|---|
| list | n | n | y | y | list block есть, но items=4 (<5); items — объекты |
| compare | y | n | y | y | table-like сравнение Postgres/Mongo |
| howto | n | n | y | y | только paragraphs, без steps |
| code | n | n | y | n* | 7× `code` blocks с **пустым** `text`; код утёк в paragraph |
| explain | y | n | y | y | HITL объяснение ок |
| fields (QX-77) | y | n | **y** | y | `QX-77` сохранён |

\*locale `p6_code`: в артефакте `locale_ok=n` (не `ru*`).

---

### Итог (прямые ответы)

| Вопрос | Ответ | Число/evidence |
|---|---|---|
| Правильно отвечает? | **partial** | Phase1: 4/5 success (+howto failure status); Phase3: 2/3 hard facts (3a,3c); 3b partial |
| Держит диалог? | **partial** | 1/3 pass (2a); 2b fail leak; 2c fail recall |
| Понимает контекст? | **partial** | 3a pass, 3c pass, 3b anti-fab ok / explicit no-data fail → ~2.5/3 |
| Harness работает? | **yes** | 34/34 traces с `agent.run` / guardrails; handoff metrics enum-clean |
| Neo4j пишет MemoryFact? | **no** (в live chat) | delta=0; extract→medium only; promote required |
| Neo4j пишет Relationships? | **no** | delta=0; baseline rels empty |
| Структурирует ответы? | **partial** | ~2/5 Phase6 strict (compare+explain); list/howto/code gaps; field preserve ok |

---

### Найденные gaps (без правок)

1. **P0 — Formatter empty code blocks / `formatter_output_invalid`:** p1_howto `status=failure` при валидных steps; p6_code — code blocks с `text=""` (код в paragraph). Ломает контракт ContentDocument для UI/клиентов.
2. **P0 — Neo4j не растёт из live chat:** ожидаемо при off-graph MK + promote-only; но продуктовый вопрос «пишет ли ассистент в Neo4j» = **нет** без отдельного promote/trigger UX.
3. **P1 — In-session long-dialog fact loss (2c):** после 10+ ходов BGT-42 не возвращается; T1 увёл в HITL save вместо dialog retention.
4. **P1 — Correction leak (2b):** правильный VEGA-9 + утечка ORION-7 в note.
5. **P1 — Cross-thread medium bleed + false “текущая сессия” (5 readback):** BGT-42 всплыл в новом thread; атрибуция к текущей сессии неверна.
6. **P1 — Anti-fabrication 3b soft:** нет QX-77 (хорошо), но вместо явного «нет данных» — clarify menu.
7. **P2 — Trace backend degraded:** без OTEL/Langfuse нет UI span по `trace_id`; верификация только через docker logs + metrics.
8. **P2 — Relationships отсутствуют** даже на baseline promote facts (0 рёбер) — graph edges не используются/не пишутся.
9. **P2 — `kind` в Neo4j = preference/fact**, не ADR-assert `incident|episode` для новых нод (новых нод нет; legacy kinds = MemoryType).
10. **P3 — tokens_in/out** не экспонируются в `FormatterTaskResult` — нельзя закрыть метрику Phase1 без отдельного cost/telemetry API.

---

### Что требует решения до следующего аудита

**P0**
1. Починить Formatter code/steps serialization (`formatter_output_invalid`, пустые `code.text`).
2. Явно зафиксировать/реализовать продукт-контракт: когда medium extract → promote → Neo4j, и как UI/чат это триггерит (не молча ждать cron).
3. Закрыть cross-thread attribution: medium recall не должен маскироваться под «текущую сессию».

**P1**
4. Dialog-window retention для user-stated facts без обязательного HITL на каждом «запомни» (или честный UX + card в ответе process).
5. Correction policy: не цитировать отвергнутое значение без нужды.
6. 3b: при отсутствии знаний — явный no-data, не только clarify.
7. Поднять OTEL/Langfuse для audit-grade span fetch по `trace_id`.

**P2**
8. Relationships / graph edges strategy (сейчас пусто).
9. Экспорт token usage в chat response или timeline.

---

### Артефакты для закрытия W10

| Требование | Путь |
|---|---|
| Phase 0–7 report | этот файл |
| Phase 2 transcripts | `artifacts/phase2.json` |
| Phase 5 cypher+raw | `artifacts/phase5.json` |
| Phase 4 traces | `artifacts/traces/*.log` + `phase4.json` |
| Per-turn request/response | `artifacts/turns/*.json` |
| Runner | `run_w10_verification.py` |

**Вердикт одной строкой:** ассистент через live chat **отвечает и проходит harness**, **частично** держит короткий диалог и использует attachment/in-session факты, **не пишет MemoryFact/Relationships в Neo4j из чата** (extract→medium; promote отдельно), со структурными дырами Formatter и утечками correction/cross-thread.
