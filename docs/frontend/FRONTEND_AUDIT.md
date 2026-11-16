# Frontend audit: `web/` vs канон `web-embed-assistant`

**Дата:** 2026-11-03  
**SoT:** `.cursor/plans/web-embed-assistant.md`, `docs/embedded-assistant.md`, правило `084`  
**Объект:** `web/` (React 19 + Vite + `@palatium/contract`)  
**Статус вердикта:** Track I (виджет) **в основном закрыт**; «переписать чат с нуля» / Module Federation / WS→SSE для ответа — **не требуется**.

---

## 1. Текущее состояние (факты инспекции)

| Критерий канона | Факт в `web/` | Статус |
|---|---|---|
| React 19 | `package.json`: `react` / `react-dom` `^19.3.0` | ✅ |
| Vite + IIFE WC | `vite.config.wc.ts` (`inlineDynamicImports`, `es2022`, single-file) | ✅ |
| `<palatium-assistant>` + Shadow DOM | `src/widget.tsx`: `attachShadow({ mode: 'open' })`, `adoptedStyleSheets`, CSS `?inline` | ✅ |
| Dual entry | `main.tsx`/`App.tsx` — SPA/dev; `widget.tsx` — embed entry | ✅ ожидаемо |
| Handshake 500 ms | `lib/hostContext.ts`: `CONTEXT_TIMEOUT_MS = 500`, `__palatiumSedContext`, `sed:assistant-context-requested` | ✅ |
| События токена | Контракт: `sed:auth-token-refreshed` / `sed:auth-token-requested` (`SED_EVENTS`) | ✅ |
| Токен только в памяти | `runtime/auth.ts` module var; unit `tests/unit/auth.test.ts`; grep storage в `src/` — только комментарии | ✅ |
| Chat streaming | `api/client.ts` → `POST /intents/process/stream` (SSE): `hop`, `document_title`, `block_delta`, `text_delta`, `answer_delta`, `result`, `done`, `error` | ✅ Hybrid SSE |
| WebSocket | `lib/sessionSocket.ts` + `ChatShell` — **только** `/ws/sessions/{thread}` (subscribe/ping), **не** стрим ответа | ✅ отдельный трек (канон) |
| HITL UI | `HitlCards` + `lib/hitl.ts` из `result.hitl_cards` / Formatter | ✅ |
| Citations | `CitationSources` + `SourcePanel` (W3b-2) | ✅ |
| i18n RU/EN | `i18n/{index,messages}.ts`, `formatNumber`/`formatDateTime` | ✅ |
| a11y | Playwright axe (`e2e/a11y.spec.ts`), LiveAnnouncer, keyboard E2E | ✅ |
| Bundle budget | `scripts/widget-release.mjs` `BUDGET_KIB = 224`; артефакт `release.json`: **~209.8 KiB gzip** / 224 | ✅ в бюджете плана |
| CEM / SRI | `custom-elements.json`, `build:widget` + `verify:widget` | ✅ |
| `sed:action-requested` | каталог в `@palatium/contract`; **виджет не эмитит** (нет SED doc refs / нет consumer у СЭД) | ⚠️ осознанный defer |

Точки входа:

- Embed: `src/widget.tsx` → `customElements.define(ASSISTANT_TAG, …)`
- Dev SPA: `src/main.tsx` → `#root` + `App`
- Standalone host mock: `standalone.html` + `npm run dev:standalone`

---

## 2. Расхождения: промпт аудита vs канон проекта

Ниже — **не баги кода**, а ложные ожидания, которые нельзя чинить «по тексту задания», иначе сломаем SoT.

| Ожидание в запросе аудита | Канон / код | Действие |
|---|---|---|
| Событие `sed:token-refreshed` | Канон: **`sed:auth-token-refreshed`** | Не переименовывать |
| HITL write → `sed:action-requested` + `requiresConfirmation` + модалка | HITL write = **карточки с сервера** (`HitlCards`). `sed:action-requested` = навигация СЭД (`open_document` / `navigate` / `search`), эмиссия отложена (§8.2 `embedded-assistant.md`) | Не смешивать оси |
| Бюджет **150 KiB** gzip | План: потолок **224 KiB** (2026-10-22); сейчас ~210 KiB | Не ронять сборку «ради 150» без решения |
| «Если WS — переписать на SSE» | Ответ уже SSE; WS — session keepalive | Не удалять session socket |
| Module Federation | Отвергнут: WC + IIFE | Не предлагать |

Дрейф документации (мелкий):

| Где | Что | Правка |
|---|---|---|
| `084-frontend-quality.mdc` §бюджет | всё ещё пишет «150 KiB» в одном месте | выровнять на `BUDGET_KIB=224` + ссылка на план |
| Статус-таблица плана (верх) | исторический замер 142/150 | оставить историю; актуальный потолок уже в §ниже (224) |

---

## 3. Реальные остатки (gap) относительно канона

| ID | Gap | Приоритет | Блокер |
|---|---|---|---|
| G1 | Производитель `sed:action-requested` не включён | P2 | Ответ СЭД + EDMS search/citations (doc id в ответе) — Track II / §5.16 |
| G2 | Host-side consumer `sed:action-requested` | P2 | Команда СЭД (не наш репо) |
| G3 | Документационный дрейф бюджета 150 vs 224 в `084` | P3 | нет |
| G4 | Standalone SPA (`main.tsx`) vs widget — два контура | — | Не gap: оба нужны; гейты CI гоняют widget path |

**Нет gap’ов:** React 18→19, Shadow DOM, handshake, token storage, SSE Hybrid для чата, citations UI, RU/EN, axe E2E, IIFE сборка.

---

## 4. План правок (конкретные файлы)

### 4.1. Сейчас (без СЭД) — docs + mock-host

1. **`084-frontend-quality.mdc`** — ✅ бюджет **224 KiB gzip** (выровнено 2026-11-03).  
2. Этот файл — SoT аудита; не плодить `AUDIT.md` в корне.  
3. Mock-стенд — расширен `web/standalone.html` (не второй `dev-harness/`).

**Не делать сейчас:** правки `ChatShell` SSE/WS, новый HITL через CustomEvent, Module Federation, миграция React, эмит `sed:action-requested`.

### 4.2. После ответов СЭД + EDMS read path (не frontend-only)

1. Когда в `result` / citations появятся SED `document_id`:  
   - эмит `SED_EVENTS.ACTION_REQUESTED` из UI цитат/кнопок (кандидат: `CitationSources.tsx` / тонкий helper рядом с contract);  
   - только типы из `@palatium/contract` (`AssistantAction`);  
   - E2E: `e2e/host.spec.ts` + mock host listener.  
2. HITL для `archive_document` остаётся **серверными карточками** + Host interrupt — **не** через `sed:action-requested`.

### 4.3. Регрессии (уже есть — не плодить дубли)

| Проверка | Команда / файл |
|---|---|
| Token not in storage | `tests/unit/auth.test.ts` |
| Handshake / tenant | `e2e/host.spec.ts`, `e2e/contract.spec.ts` |
| SSE typed frames | `tests/integration/process-stream-typed.test.ts` |
| a11y Shadow DOM | `e2e/a11y.spec.ts` |
| Bundle + SRI | `npm run build:widget` / `verify:widget` |
| Delivery gate | `tests/unit/test_frontend_widget_delivery.py` |

---

## 5. Краткие ответы на шаги ТЗ

1. **Инспекция:** React 19, Vite WC IIFE, `<palatium-assistant>` + Shadow DOM — на месте.  
2. **Handshake:** `__palatiumSedContext` + 500 ms + события канона — на месте; имя токена = `sed:auth-token-refreshed`.  
3. **Streaming:** чат = SSE Hybrid; WS = sessions only — **не переписывать**.  
4. **HITL / citations / i18n / a11y:** реализованы по канону; `sed:action-requested` — defer, не баг UI.  
5. **Сборка:** CSS inline + adoptedStyleSheets; gzip ~210 / 224 KiB.

---

## 6. Рекомендация владельцу

Frontend embed **не** является текущим блокером Big Tech / JavaEdms. Фокус интеграции — ответы СЭД по `docs/integration/INTEGRATION_CONTRACT.md` и Track II (EDMS MCP). Дальнейшие правки кода виджета (эмит `sed:action-requested`) без ответов СЭД бессмысленны. Бюджет в `084` выровнен на 224 KiB (2026-11-03).

---

## 7. Как тестировать локально (Mock-стенд)

**SoT стенда — `web/standalone.html`.** Отдельный `web/dev-harness/` **не** заводим (второй стенд = рассинхрон с E2E/Playwright, 050). Стенд уже имитирует хост СЭД: handshake, preload `__palatiumSedContext`, refresh по 401, смена документа, `sed:thread-changed`.

### Запуск

```bash
# API на :8000 (dev-token). Без бэкенда кнопка «Отправить контекст» покажет ошибку mint.
cd web
npm run dev:standalone
# → http://127.0.0.1:5174/standalone.html
# preload-контекст до define: http://127.0.0.1:5174/standalone.html?preload
```

Собранный IIFE (как в СЭД): `npm run build:widget`, затем подключить `dist-widget/palatium-assistant.v*.iife.js` на любой статике — сценарии событий те же.

### Чек-лист на стенде

| Кнопка / зона | Что проверяет |
|---|---|
| «Отправить контекст host'а» | `sed:context-changed` → режим host, токен в памяти |
| «Обновить токен» | ручной `sed:auth-token-refreshed` |
| «Испортить токен (401 → refresh)» | виджет шлёт `sed:auth-token-requested`, хост отвечает refresh |
| Лог под панелью | события host↔виджет; `sed:action-requested` — пока пусто (G1) |
| Красный фон / Comic Sans у body | **не** должны появиться внутри панели/лончера (Shadow DOM) |
| E2E без ручных кликов | `cd web && npm run test:e2e` (матрица + host + a11y) |
