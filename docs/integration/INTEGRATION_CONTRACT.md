# Draft: контракт интеграции Palatium-AI ↔ Канцлер NEXT (JavaEdms)

**Статус:** DRAFT для подтверждения командой СЭД (не норматив платформы).  
**Дата сверки:** 2026-11-03.  
**Источники (локальный read-only reference):** бэкенд/фронт JavaEdms; гипотезы из junior-прототипа `edms-ai-assistant` — только там, где явно помечено.  
**MCP-пины Host (уже зафиксированы):** `mcp:edms.search_documents` (read), `mcp:edms.archive_document` (write, HITL).

Правило для рецензентов СЭД: подтвердите или исправьте строки ниже. Мы **не** выдумывали URL; при конфликте junior vs JavaEdms побеждает JavaEdms.

---

## 0. Соответствие MCP-пинов → API СЭД (предложение)

| MCP pin | Предлагаемый SoT endpoint | Side effect |
|---|---|---|
| `search_documents` | **A (предпочтительно):** `GET api/full-search` — полнотекст; **B (fallback):** `GET api/document` — список по `DocumentFilter` | read |
| `archive_document` | **A:** `PUT api/document/{documentId}/archive` — один документ; **B:** `PUT api/document/archive` — batch | write |

Палатium pin сегодня принимает только `query` / `document_id` (`domain/mcp/external_schemas.py`). Расширение схемы — только после вашего «да» на поверхность.

---

## 1. Поверхность (Endpoints)

### 1.1. Поиск — вариант A: полнотекст

**JavaEdms SoT:** `FullSearchController` → `@RequestMapping("api/full-search")`.

| | |
|---|---|
| Method / path | `GET /api/full-search` |
| Query | `search` (String, обязателен), `docInArchive` (`DocArchiveStatus`: `BASE` \| `ARCHIVE` \| `ALL`), Spring `page` / `size` / `sort` |
| Auth | `@AuthenticationPrincipal CustomUserDetails` (нужен валидный JWT) |
| Feature flag | `@ConditionalOnProperty(value = "opensearch.enabled", havingValue = "true")` — **без OpenSearch контроллер не поднимается** |
| Response | тело из `FullSearchService.search(...)` (Spring page/slice; OpenAPI schema в контроллере — `String`, фактическая структура — у сервиса) |

Расширение: `GET /api/full-search/ext` — тот же контроллер, тело фильтра = `DocumentFilter` + `Pageable` (валидатор `DocumentFilterValidator`).

**Фронт СЭД (канон параметра):** `frontend/.../fullTextSearchApi.js` шлёт `{ search, docInArchive, page, size, sort }`.

**Junior (гипотеза, частично REJECT):**  
- вызывает `GET api/full-search` с параметром **`inArchive=true|false`** (`document_query_params.build_full_search_query_params`);  
- фронт СЭД и контроллер ждут **`docInArchive=BASE|ARCHIVE|ALL`**;  
- во фронте есть legacy-метки `true`/`false` (`DOC_ARCHIVE_LEGACY_*`), но SoT-enum — `BASE`/`ARCHIVE`/`ALL`.  
**Вывод для контракта:** использовать `docInArchive`, не boolean `inArchive`. Junior-костыль не копировать.

### 1.2. Поиск — вариант B: список документов

**JavaEdms SoT:** `DocumentController.getAll` → `@GetMapping` на `api/document`.

| | |
|---|---|
| Method / path | `GET /api/document` |
| Query | flat-поля `DocumentFilter` + `Pageable` + флаг `full` (boolean; `true` → `findAll`, иначе `findAllShort`) |
| Auth | JWT → `CustomUserDetails` |
| Response | slice/page документов (`DocumentDto` / short-модель) |

**Junior:** `GET api/document` + flat `DocumentFilter` + `page`/`size`/`listAttribute` (`search_list.search_documents`).  
`listAttribute` есть в SPA `documentApi.js`; в сигнатуре `getAll` отдельного `@RequestParam listAttribute` **нет** — параметр, скорее всего, игнорируется Spring или биндится иначе. **Open question к СЭД:** нужен ли `listAttribute` для API-клиентов.

Гидратация карточки после full-search: junior делает `GET api/document/{id}?includes=...` (`get_document_metadata`). SoT: `GET api/document/{id}`.

### 1.3. Архивация — один документ

**JavaEdms SoT:**

```
PUT /api/document/{documentId}/archive
Body: { "inArchive": true|false }   // DocumentArchiveRequest
```

- `inArchive=true` → `documentService2.inArchive(...)`  
- `inArchive=false` → `extractArchive(...)`  
- Аннотация: `@CheckDocumentPermission(operationType = DOCUMENT_IN_ARCHIVE_UPDATE)`  
- HTTP 200; тело ответа в коде контроллера фактически пустой `ok().build()` (результат сервиса не возвращается клиенту — зафиксированный quirk SoT).

**Junior:** тот же URL/метод/JSON (`set_archive_state`) — **совпадает с SoT**.

### 1.4. Архивация — batch

| | |
|---|---|
| В архив | `PUT /api/document/archive` body `{ "ids": [UUID, ...] }` → `CountResult` |
| Из архива | `DELETE /api/document/archive` body `{ "ids": [...] }` → `CountResult` |
| Authority | `@PreAuthorize("hasAuthority(...Permission.UPDATE_DOCUMENT_IN_ARCHIVE_VIEW)")` |

**Junior:** те же пути (`archive_documents_batch` / `extract_archive_batch`) — **совпадает**.

**Маппинг на pin `archive_document`:** предлагаем single-doc `PUT .../{id}/archive` с `{ "inArchive": true }` (HITL на Host). Batch — отдельный сценарий, не в текущем pin.

### 1.5. Auth заголовок (транспорт)

| Источник | Факт |
|---|---|
| JavaEdms | `JwtAuthenticationFilter` → `SecurityUtils.resolveBearerToken(request)` читает header `Authorization`, ожидает префикс `Bearer ` |
| Junior | `authorization_headers(token)` → `Authorization: Bearer {token}` |
| Base URL (junior settings) | `EdmsSettings.base_url` default `http://127.0.0.1:8098` — **не SoT стенда**, только локальный дефолт прототипа |

**Вывод:** On-Behalf-Of через user JWT Bearer — подтверждается кодом. Cookie как основной путь API для этих контроллеров **не** найден.

---

## 2. Authority (права)

Источник enum: `eu.iba.edms.security.model.Permission`.

| Операция | Что видно в коде | Константа / механизм |
|---|---|---|
| Batch archive / extract | явный `@PreAuthorize` | `UPDATE_DOCUMENT_IN_ARCHIVE_VIEW` («В архив (из архива)») |
| Single archive | `@CheckDocumentPermission(DOCUMENT_IN_ARCHIVE_UPDATE)` | per-document ACL через `DocumentPermissionService` (не простой `@PreAuthorize` на Permission-enum) |
| List / full-search | **нет** `@PreAuthorize` на контроллере | доступ аутентифицированного пользователя + фильтрация в сервисе; глобальное чтение контура: `READ_ALL_ORGANIZATION_DOCUMENT` («Чтение всех документов контура СЭД») — используется в `DocumentServiceImpl` (комментарий про выдачу документов текущей организации) |
| Создание документа (вне текущего pin) | `@PreAuthorize` | `CREATE_DOCUMENT` |

**Draft для W10b (нужно подтверждение СЭД):**

- `search_documents` → минимум: аутентифицированный пользователь; опционально требовать `READ_ALL_ORGANIZATION_DOCUMENT` **только** если продукт хочет org-wide search без обычного ACL. Иначе **не** дублировать ACL на MCP: доверять фильтрации `findAll` / `FullSearchService`.  
- `archive_document` → Host-gate: наличие `UPDATE_DOCUMENT_IN_ARCHIVE_VIEW` **и/или** успешный per-doc `DOCUMENT_IN_ARCHIVE_UPDATE` (как в API). Точный AND/OR — **Open question**.

События аудита действий пользователя (не Permission): `UserActionType.DOCUMENT_IN_ARCHIVE` / `DOCUMENT_EXTRACT_ARCHIVE`.

---

## 3. Scope / метаданные / Strategy для RAG

### 3.1. Как СЭД уже фильтрует «своё»

- `DocumentFilter.ioOption`: `SELF` | `IO` | `SUBORDINATES` | `SELF_AND_IO` | `SUBORDINATES_AND_SELF_AND_IO` (default `SELF_AND_IO`).  
- Tenant/org документа: `Document.organizationId` (`organization_id`).  
- Номенклатура: `nomenclatureAffairId` + `nomenclatureAffairOrgId`.  
- Department на документе — **не одно поле `departmentId`**, а роли участников (initiator / who_signed / chairperson / secretary `departmentId` embed).  
- Архивный срез: `docInArchive` = `BASE` | `ARCHIVE` | `ALL`.

**Вывод:** scope по подразделениям/IO **реализован на API** через `DocumentFilter` + user principal, а не только на фронте. Дефолт MCP: **не дублировать ACL** — вызывать API от имени пользователя; фильтр `ioOption` передавать только если продукт явно просит.

### 3.2. Индексировать в `knowledge.*` или дергать API?

**Факт Palatium `knowledge.documents` / `knowledge.chunks` сейчас:**  
`user_id`, `thread_id`, `source_document_id`, `title`, `mime_type`, … — **нет** `organization_id` / `department_id` / nomenclature SED-полей.

**Рекомендация Draft (нужно «да/нет» от СЭД):**

1. **Hot path поиска документов СЭД** — live API (`full-search` если OpenSearch включён, иначе `GET api/document`).  
2. **Локальный `knowledge.*`** — только для загруженных вложений/инgest платформы; **не** зеркало всего архива СЭД без отдельного ETL-контракта.  
3. Если всё же нужен Scope-RAG по выгрузке — СЭД должна подтвердить поля выгрузки: минимум `id`, `organizationId`, поля department/nomenclature, которые они считают SoT для ACL (см. Open questions). **До подтверждения колонки в `knowledge.*` не добавляем.**

### 3.3. OpenSearch

`FullSearchController` живёт только при `opensearch.enabled=true`.  
**Open question:** на стендах Канцлера OpenSearch всегда включён? Если нет — pin `search_documents` обязан уметь fallback на `GET api/document`.

---

## 4. Auth & Audit

### 4.1. Auth

- Header: `Authorization: Bearer <access_token>`.  
- Фильтр: `JwtAuthenticationFilter` (pre-auth principal = raw JWT string после снятия `Bearer `).  
- Доп. header, который читает SecurityUtils: `X-Req-attempt-count` (счётчик попыток) — не correlation id.  
- `User-Agent` используется в `OauthController` (логин), **не** как обязательный header для document API.

### 4.2. Audit

| Найдено | Назначение |
|---|---|
| `GET/… api/user-action` (`UserActionController`) | **чтение** журнала действий (не write от AI) |
| `EmployeeAuthorizationAuditController` | аудит **авторизаций** сотрудника |
| `UserActionType.DOCUMENT_IN_ARCHIVE` | тип события при архивации (пишется сервисом СЭД при штатном API) |

**Отдельного `POST /api/audit/ai-action` в контроллерах не найдено.**  
**Draft:** достаточно вызывать штатные API от имени пользователя — аудит архивации ляжет через существующий user-action pipeline СЭД. Отдельный AI-audit endpoint — только если СЭД его потребует (сейчас в коде нет).

---

## 5. Лимиты

В JavaEdms **не найдено** HTTP rate-limit / RPS квот на document/full-search API (есть throttle только у **reindex** job OpenSearch).  
Timeouts в junior: `EdmsSettings.timeout=30`, `long_timeout=120` — **не** контракт СЭД.  
**Open question:** RPS и p95/max latency search на стенде.

---

## 6. Явные пробелы (Open Questions для команды СЭД)

Ответьте «да/нет» или конкретной строкой:

1. **Поверхность search:** подтверждаете ли маппинг `search_documents` → `GET api/full-search` (+ fallback `GET api/document` при `opensearch.enabled=false`)?  
2. **Параметр архива в search:** канон `docInArchive=BASE|ARCHIVE|ALL` (не boolean)? Какой default для ассистента (`BASE`)?  
3. **OpenSearch:** обязателен ли на prod/stage?  
4. **Архивация pin:** single `PUT .../{id}/archive` с `{inArchive:true}` — достаточно для v1? Batch нужен?  
5. **W10b:** для search достаточно «любой authenticated», или обязателен конкретный `Permission`? Для archive — достаточно ли `UPDATE_DOCUMENT_IN_ARCHIVE_VIEW` на Host до вызова?  
6. **Scope:** подтверждаете «не дублировать ACL в MCP, полагаться на API + JWT пользователя»? Нужен ли явный `ioOption=SUBORDINATES_AND_SELF_AND_IO`?  
7. **RAG:** live API only на v1, без ETL в `knowledge.*`? Если ETL нужен — список полей + endpoint выгрузки.  
8. **AI-audit:** хватает штатного user-action при вызове API, или нужен отдельный endpoint (его нет в текущем дереве)?  
9. **Correlation:** обязателен ли конкретный header (имя/формат)? В document API не найден.  
10. **RPS / timeout:** цифры для Circuit Breaker клиента.

---

## 7. Что сознательно не берём из junior

| Junior | Решение |
|---|---|
| `inArchive` bool на full-search | REJECT → `docInArchive` enum |
| Default base URL `127.0.0.1:8098` | не контракт; URL только env |
| Широкий набор write/BPMN/control tools | вне пинов v1; не онбордить в 070 без обсуждения |
| Локальная KB junior (Confluence/SharePoint) | не API Канцлера; вне scope |

---

## 8. Следующий шаг после подтверждения

После ответов на §6 п.1–7: Host оставляет имена пинов; MCP-адаптер (волны 092 W1–W2) реализует **только** подтверждённые URL/параметры; W10b маппит authority; Scope-RAG / колонки `knowledge.*` — **только** если п.7 = ETL.

*Документ не является разрешением писать MCP-код или менять JavaEdms.*
