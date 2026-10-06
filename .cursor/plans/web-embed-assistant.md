# План: embeddable AI Assistant `<palatium-assistant>` (две команды: виджет + интеграция)

Обновлено: 2026-09-29.
Вход 1: черновик «Web-реализация embeddable AI Assistant Palatium-AI» (переписан в Приложении A).
Вход 2: расширенная инструкция «аудит, проектирование и реализация» (Фазы 1–4) — разобрана в §1.4; исправленный промпт — Приложение B.
Факт-чек: `web/` (исходники), `src/palatium_ai/` (бэкенд), `mcp_servers/edms/JavaEdms/{frontend/gtb,edms}` (read-only, 090).
Статус: **PLAN**. Это вход/навигация, **не** норматив. Норматив после реализации — `084-frontend-quality` (W4 плана `cursor-rules-hardening`) + `070`/`020`/`060`/`030`.

Две зоны ответственности:
- **Track I — виджет** (W0–W9): `web/`, `@palatium/contract`, `<palatium-assistant>`.
- **Track II — интеграция и бэкенд** (W10–W13): capability whitelist, scope-RAG, персонализация, аудит — **только после** правки 070 (закрытый перечень инструментов), не ad-hoc.

---

# Статус реализации (обновляется по ходу волн)

Обновлено: 2026-09-30. Track I закрыт на нашей стороне: реализованы **W0–W8** (виджет) и **W9** (интеграционный
пакет), по ходу разбора закрыты вопросы, считавшиеся продуктовыми (§5 п.3 — локаль `GE`, §5 п.5 — непрерывность
диалога, §5 п.9 — производитель `sed:action-requested`, §5 п.14 — версия OWASP LLM), и исправлены два найденных
при этом дефекта (утечка локали браузера, потеря диалога при перезагрузке). Open items требуют стенда
СЭД или решения команды СЭД (§5, §8 `docs/embedded-assistant.md`); Track II (W10–W13) начат: предусловие
(правка правила 070) снято — правило приведено к коду (`PlatformToolPin` + `ToolExecutor`), W10a (генератор
authority + drift-гейт) сделан, W11 сделан целиком (форматы локали, обращение по имени, непрерывность диалога).
Дальше Track II упирается в ответы команды СЭД (§5 п.11 — протокол стриминга, §5 п.12 — источник имён ролей,
§5 п.16 — имена инструментов и маппинг tool→authority).

| Что | Где | Состояние |
|---|---|---|
| Контракт `@palatium/contract` | `web/packages/contract/src/index.ts` | ✅ `SedContext`/`SedUser`/`SedPermissions`/`SedDocumentRef`/`SED_EVENTS`/`ASSISTANT_{API,WS}_PATH`, `isSedContext` (валидация на границе), `toBcp47`, `buildDepartmentScope`; W9: `AssistantAction` (закрытый каталог) + `isAssistantAction`, `checkTenantConsistency`/`tokenTenantId`/`jwtClaims`; W11: `preferredName`, `SedContext.threadId` + `sed:thread-changed` + `normalizeThreadId`/`THREAD_ID_MAX_LENGTH` (лимиты — как у сервера) |
| Workspaces | `web/package.json` (`workspaces: ["packages/*"]`), `web/tsconfig.json` (`include: packages/contract/src`) | ✅ `npm install` линкует пакет |
| Runtime (in-memory) | `web/src/runtime/{auth,store,endpoints,useRuntime}.ts` | ✅ токен в памяти, `hostStatus`, ids, локаль, `panelOpen`; адреса REST и WS — из одной базы (W9); W11: `userName` из контекста, `threadId` + `threadFromHost` (тред host'а принимается, свой объявляется) |
| Event bridge + handshake | `web/src/lib/hostContext.ts` | ✅ `sed:context-changed` / `token-refreshed` (window **и** элемент), `sed:context-requested`, `window.__palatiumSedContext`, окно 500 мс; W9: отбрасывание контекста с несогласованным tenant'ом (`checkTenantConsistency`) |
| Web Component | `web/src/widget.tsx` | ✅ Shadow DOM `open`, `adoptedStyleSheets`, root переживает reconnect, `setContext/open/close`, `palatium:ready`, `[collapsed]`; W11: объявление тредa `sed:thread-changed` (молчит до рукопожатия, не повторяет один id, не эхает id host'а) |
| Стили Shadow DOM | `web/src/tokens.css` (`:root, :host`), `web/src/widget.css` | ✅ токены общие для app и виджета |
| Сборка IIFE | `web/vite.config.wc.ts` | ✅ single-file, `inlineDynamicImports`, `target: es2022` |
| Стенд без СЭД | `web/standalone.html` | ✅ мок-хост (в т.ч. контекст **до** загрузки), `close()`/`open()`, переключатель темы, демо `::part()` |
| Токен вне storage | `web/src/api/client.ts`, `web/src/lib/trace.ts`, `ChatShell.tsx` | ✅ grep-гейт чист (совпадения только в комментариях) |
| Без перезагрузки страницы | `ChatShell.handleNewThread` | ✅ `location.reload()` больше не вызывается |
| CEM | `web/custom-elements.json` | ✅ `npm run cem`: `tagName: palatium-assistant`, атрибуты, два `@fires` (`palatium:ready`, `sed:thread-changed`), перечень `::part()`; гейт `test_frontend_widget_delivery.py` требует оба события |
| ⏳ `sed:action-requested` | `web/packages/contract` (`AssistantAction`) | ✅ каталог ЗАКРЫТ и типизирован (W9): `open_document` / `navigate` (`SedViewKey`) / `search` — ключи разделов взяты из `frontend/gtb/src/constants/content/route.js`; эмиссия — после появления обработчика у СЭД (иначе событие без потребителя = мёртвый код), §8.2 `docs/embedded-assistant.md` |
| Темизация (W4) | `web/src/tokens.css`, `web/src/widget.css` | ✅ `data-theme="light"` (opt-in), 6 `::part()`, Google Fonts убраны |
| Motion (W5) | `web/src/styles.css` | ✅ `--ease-*`/`--duration-*`, hover-гейт 9/9, `scale(0.97)`, stagger HITL, scoped reduced-motion |
| i18n | `web/src/i18n/{index,messages}.ts` | ✅ RU/EN (тип `Record<MessageKey, string>`), 109 ключей, `{param}`-подстановка; W11: единый владелец локали для чисел/дат (`formatNumber`/`formatDateTime`) — формат следует языку интерфейса, а не локали браузера; обращение по имени — `preferredName` в контракте (`firstName` → `fullName` как есть) |
| Доставка (W7) | `web/scripts/widget-release.mjs`, `web/vite.config.wc.ts` | ✅ semver+hash в имени, SRI в `release.json`, бюджет-гейт, CEM в артефакте |
| CI виджета (W7) | `.github/workflows/ci.yml` (job `frontend`) | ✅ `npm ci` → typecheck → `cem:check` → `build:widget` → `verify:widget` → артефакт |
| Тест доставки (W7) | `tests/unit/test_frontend_widget_delivery.py` | ✅ 5 тестов: LF-правило, контракт CEM, связка скриптов, single-file+хеш, отсутствие storage/reload |
| ⏳ Линт-гейт i18n | — | ESLint во `web/` нет — «нет хардкод-строк» остаётся гейтом правила `084` (W4 hardening) |
| E2E + a11y (W8) | `web/e2e/{state-matrix,interaction,a11y,host,endpoints,contract}.spec.ts` + `mock-server.ts` | ✅ 49 тестов на `standalone.html` без backend (45 исполняются, 4 — кадры по запросу); axe WCAG A/AA в двух темах, Tab/focus в Shadow DOM, reduced motion; W9: граница доверия контекста (чужой tenant), каталог действий и локаль `GE`; W11: форматы чисел/дат, обращение по имени и непрерывность диалога — от host'а, а не от браузера |
| CI виджета (W8) | `.github/workflows/ci.yml` (job `frontend`) | ✅ + `playwright install chromium` → `test:e2e` → артефакт `playwright-report` (`always()`) |
| Визуальная сверка тем (W8) | `web/e2e/shots.spec.ts`, `web/scripts/shots.mjs` | ✅ по запросу (`npm run test:shots`) — вне CI, кадры в `web/.shots/` |
| Capability whitelist (W10a) | `scripts/gen_edms_authorities.py`, `src/palatium_ai/domain/mcp/edms_authorities.py`, `domain/mcp/edms_permissions.py` | ✅ 303 authority из enum `Permission` (291 CRUD + 12 `other`), артефакт с fingerprint, drift-гейт `--check` (референс + саморендер), 19 unit-тестов; остаток W10b — маппинг tool→authority за командой СЭД (§5 п.16) |

**Замеры (`npm run build:widget`):**

```
dist-widget/palatium-assistant.v0.1.0.CGHdi0nz.iife.js   469.16 KiB raw │ 142.44 / 150 KiB gzip (95.0%)
```

Дайджест `sha384-YNeGKFYL1rPMIE+BTbw8XkrD7IYeuurCALfLsDfu2oj7rgIXwVesi+HXTvbaVFrT`.
Воспроизводимость замерялась на W7 (четыре независимых сборки, включая после чистого `npm ci`, дали один
дайджест); замер сверху — тот же конвейер плюс проверки W9 (+1.33 KiB raw: `atob`/`TextDecoder` и разбор
контракта), W11-форматы (+0.25 KiB raw: `Intl` вместо `toLocaleString` на месте), обращение по имени
(+0.39 KiB raw: `preferredName` и приветствие) и непрерывность диалога (+0.61 KiB raw: `normalizeThreadId`,
`threadFromHost`, объявление тредa).

Бюджет 150 KiB gzip **соблюдён** без второго артефакта: ESM-вариант с lazy-load не нужен (см. 2.4).
Вклад снижен переходом `LottieSvg` → `LottieLight` (`src/icons/TokenIcon.tsx`, 161.17 → 140.43 kB gzip):
анимации статусов не используют expressions (проверено: 0 маркеров `x` в `src/lottie/*.json`),
а light-сборка не тянет `eval` — это снимает и риск для CSP страницы-хоста.
Рост на W4–W6 — оба словаря RU/EN целиком (отклонение 5); резерв до бюджета — 7.56 KiB.

**Отклонения от чернового плана (осознанные, с причиной):**

1. **Контракт — source-first, без сборки ESM+CJS+`.d.ts`.** Потребитель один (`web/`, Vite/TS), публикации пока нет;
   двойная сборка дала бы дрейф типов и рантайма. Триггер добавить сборку — когда `@palatium/contract` понадобится
   команде СЭД как npm-артефакт (§5 п.8).
2. **Токены вынесены в `web/src/tokens.css` (`:root, :host`).** Внутри shadow tree `:root` не матчится, поэтому виджет
   без собственных токенов остался бы без переменных на странице СЭД (`var(--bg)` → invalid).
3. **`LottieLight` вместо `LottieSvg`** — см. выше.
4. **`observedAttributes` = `['lang']` только.** `density` не объявлен: CSS под него не появился и в W4 — плотность сейчас не варьируется
   (светлая тема размеров не меняет). Объявлять атрибут, который никто не читает, — тот самый дефект, который план исправлял (2.3).
   Триггер — реальная потребность СЭД в компактном режиме.
5. **i18n — статические локали, без lazy-load.** Пункт W6 «lazy-локали» противоречит 2.4: single-file IIFE не может code-split'иться.
   Оба словаря (~4 kB raw) входят в бандл. Триггер пересмотра — пробитый бюджет или третий язык.
6. **Светлая тема — opt-in (`data-theme="light"`), НЕ `prefers-color-scheme`.** `prefers-color-scheme` описывает ОС пользователя,
   а не тему приложения-хоста: при тёмной ОС в светлом СЭД авто-переключение дало бы тёмный виджет в светлом интерфейсе.
   Правильный сигнал — тема хоста, поэтому её объявляет хост (атрибут на `html` или на самом элементе). Палитра светлой темы
   сверена в W8 (axe-контраст + кадры `npm run test:shots`); остаточный риск — протечка стилей светлого Bootstrap хоста,
   проверяется только на реальном СЭД-стенде (W9).
7. **`tagName` в манифесте — из литерала `define('palatium-assistant')`, а не из константы.** CEM читает `tagName` из AST вызова;
   константа дала бы в манифесте `ASSISTANT_TAG`. Рассинхрон с `@palatium/contract` закрыт `satisfies typeof ASSISTANT_TAG`
   (компилятор, а не глаз). Тот же приём для `palatium:ready`: событие эмитит свободная функция `announceReady` — иначе CEM
   писал в манифест безымянное событие (имя не строковый литерал).
8. **Публичных `::part()` шесть, а не «весь интерьер».** Отдать наружу всё — связать виджет с хостом и потерять свободу
   рефакторинга (2.6): сейчас `launcher`, `shell`, `header`, `transcript`, `composer`, `close`.
9. **Доставка — свой скрипт, а не плагин SRI.** SRI считается по ГОТОВОМУ файлу, поэтому его нельзя посчитать внутри
   сборки; попутно те же данные дают гейт бюджета и проверку CEM. Новых зависимостей ноль (`node:crypto`, `node:zlib`).
10. **`Makefile` не тронут.** Его цели — инфра/docker (`up`, `down`, `attach-*`); цикл фронтенда живёт в `web/package.json`,
    а гейты — в CI-job `frontend`. Тащить npm в Makefile = второй способ запускать одно и то же (050).
11. **Storybook не вводится — матрица состояний кодом** (`web/e2e/state-matrix.ts`, §5 п.6). Второй рантайм, второй конфиг
    сборки и ручная синхронизация с реальным виджетом ради тех же 15 состояний; в Playwright они идут против НАСТОЯЩЕГО
    элемента на стенде и проверяют, что видит пользователь.
12. **Backend для E2E не поднимается — мок-граница** (`web/e2e/mock-server.ts`). Прогон детерминирован и работает в CI без
    Postgres/Redis/LiteLLM; закрытый перечень эндпоинтов превращает «виджет ходит мимо контракта» в упавший тест.
    Триггер пересмотра — контрактные изменения бэкенда: тогда добавляется отдельный smoke против живого стека, а не
    замена этих тестов (скорость и изоляция остаются).
13. **Кадры тем — по запросу (`npm run test:shots`), не в CI.** Сравнения с базлайном нет, поэтому в CI они давали бы шум
    без сигнала; контраст держит axe, а картинки нужны человеку после правки токенов.
14. **Каталог действий для `sed:action-requested` решён нами, а не «ждали список от СЭД».** Черновик плана
    предполагал, что перечень даст команда СЭД. Вместо ожидания каталог выведен из их же кода
    (`frontend/gtb/src/constants/content/route.js`): `open_document`, `navigate` по закрытому `SedViewKey`,
    `search`. Это не «выдуманный контракт» (090): маршруты — факт из референса, а `view` объявлен ключом, а не
    путём, поэтому переименование маршрута у СЭД контракт не ломает. Эмиссия по-прежнему выключена, но по
    другой причине, чем казалось в черновике: мешает не отсутствие каталога, а отсутствие **производителя** —
    `ContentDocument.actions` в виджете не рендерится вообще (найдено при разборе), а `ActionKind` — словарь
    платформы, не СЭД. Вопрос зафиксирован отдельно (§5 п.9); сам контракт ценен и без включённого события —
    host может реализовать обработчик по скелету из §9.2.1 в любой момент.
15. **Tenant-консистентность проверяется в виджете.** `checkTenantConsistency` отбрасывает контекст, где
    `scope.tenantId`, `user.orgId` и claim токена расходятся. Довод: tenant на сервере берётся из токена, поэтому
    расхождение = «UI показывает данные одной организации, сервер отвечает от имени другой». Проверка стоит
    ~1.3 KiB raw, живёт в контракте (нужна обеим сторонам) и снимает класс ошибок интеграции, который иначе
    выглядел бы как баг виджета. `payload: Record<string, unknown>` в `AssistantAction` заменён размеченным
    объединением — сырой dict на межкомандной границе прямо запрещён (050).

**Следующий шаг:** Track I закрыт на нашей стороне. Закрыты и вопросы, считавшиеся продуктовыми: локаль `GE`
(§5 п.3 — найден и исправлен реальный дефект с языком браузера, регрессия в `host.spec.ts`), непрерывность
диалога (§5 п.5 — `SedContext.threadId` + `sed:thread-changed`), производитель `sed:action-requested`
(§5 п.9 — упирается в retrieval/EDMS MCP, а не в решение о UX) и версия OWASP LLM (§5 п.14). Дальше — Track II
(W10–W13): правило 070 приведено к коду, W10a (генератор authority) и W11 сделаны целиком; остаток Track II
требует ответов команды СЭД (§5 п.11 — протокол стриминга, §5 п.12 — источник имён ролей, §5 п.16 — имена
инструментов и маппинг tool→authority). На нашей стороне без внешних ответов закрытых пунктов не осталось.

**Проверено (локально, полная последовательность CI-job `frontend`):** `npm ci` ✅ (workspace-линк `@palatium/contract` создаётся) ·
`npm run typecheck` ✅ · `npm run cem:check` ✅ · `npm run build:widget` ✅ (142.44 / 150 KiB gzip) · `npm run verify:widget` ✅ ·
`npm run test:e2e` ✅ (45 passed + 4 кадра по запросу пропущены, прогон повторён без флаки) · `npm run build` (app) ✅ · dev-сервер отдаёт `standalone.html` и трансформирует модули ✅ ·
бандл чист от `localStorage`/`sessionStorage`/`location.reload`/`fonts.googleapis` ✅ · hover-гейт 9/9 · `transition: all` — 0 ✅.

**Гейты проверены отказом, а не только успехом:** подмена байта бандла → `verify:widget` падает (exit 1); бюджет 100 KiB →
`build:widget` падает (exit 1); дрейф JSDoc в `widget.tsx` → `cem:check` падает (exit 1), после откатов — снова 0.

Доставка закреплена тестом `tests/unit/test_frontend_widget_delivery.py` (5 тестов): LF-правило `web/**`, контракт из
`custom-elements.json` (тег, `lang`/`collapsed`, два события — `palatium:ready` и `sed:thread-changed` — шесть `::part()`),
связка скриптов сборки с гейтами,
single-file IIFE с версией и хешем в имени, отсутствие `localStorage`/`sessionStorage`/`document.cookie`/`location.reload`
в рантайме. Проверено, что тест не вакуумный: поломка трёх инвариантов даёт 3 падения, откат — 5 зелёных.

Браузерная проверка Shadow DOM (лончер, `::part()`, светлая тема, reduced-motion) **не выполнена**: MCP-инструменты браузера
заблокированы RBAC-хуком (не входят в allowlist) — владельцем этой проверки остаётся гейт W8 (Playwright).

---

## 0. North star и границы

```
СЭД «Канцлер» (host, React 17 · Redux · Bootstrap 4 · Vite 8)
  ├─ dispatchEvent('sed:context-changed', SedContext)      ← токен, user, права, документ
  ├─ слушает 'sed:assistant-context-requested' → отвечает контекстом
  └─ <palatium-assistant>  (Web Component, Shadow DOM open)
        └─ собственный React 19 runtime (не делит React с host)

        CustomEvent → in-memory bridge → fetch/WebSocket
                                         ▼
                          Palatium-AI (FastAPI)  /api · /ws/sessions/{thread}
```

- Виджет **не переиспользует** React host'а и не полагается на его DOM: СЭД на React 17, платформа — на 19, изоляция обязательна.
- Токен живёт **только в памяти** виджета. Один storage-ключ = дефект.
- Домен событий (`sed:*`) — контракт **между двумя командами**; его нельзя менять «молча в PR» (005).
- Разработка без СЭД обязательна: `standalone.html` + mock-контекст (иначе каждая правка блокируется чужой командой).

**Вне scope:** бэкенд-контракты (`/intents`, `/hitl`, `/memory`, `/attachments` — 070/020), `BlockRenderer`/`HitlCards`/`MemoryActions` (переписывать не нужно), SSR/RSC, новый стейт-менеджер (Redux/zustand — YAGNI), motion-библиотека (жестов, требующих spring, в виджете нет).

---

## 1. Вердикт по черновику (fact-check)

### 1.1. Фактические ошибки — исправить обязательно

| Черновик | Факт | Что делать |
|---|---|---|
| React **19.2.8**, Vite **7.3.6** | `web/package.json`: `react ^19.1.1`, `vite ^7.1.5`, `typescript ~5.9.2` | Писать диапазоны из `package.json`, не выдуманные пины |
| «Уже есть **Shadow DOM-ready** структура» | `attachShadow` / `customElements` / `shadowRoot` — **0 совпадений** в `web/src`. `WidgetEmbed.tsx` — рендер блока `ContentDocument`, не Web Component | Shadow DOM **не начат**; это W1, а не «дожать» |
| Ссылки на `index-Bk1Two3_.css`, `index-B5NgVZD_.js` | Это артефакты `web/dist/` (dist в репо есть, но хеши нестабильны) | В аудите ссылаться на **исходники**, не на имена из `dist/` |
| «CSS не изолирован в Shadow DOM» как отдельный пункт | Следует из «Shadow DOM ещё нет» | Объединить; не выдавать за два пробела |
| `localization: string`, «`locale` из `SedContext.user.localization`» | `Localization` (JavaEdms) = enum **`RU\|EN\|GE`** — это **не** BCP-47 | Ввести явный маппинг enum → `ru-RU`/`en-US`/`?`. `GE` **проверить** (немецкий или Грузия) — §5 п.3 |
| `post: { id, postCode, name? }` | `PostDto`: `id: Long`, **`postName`**, `postCode`, `createDate` | Исправить поле |
| `country: { alphaCodeTwo, alphaCodeThree, code }` | `CountryDto`: `+ id`, `shortName`, `fullName`, `active`, `createDate`; `code` ∈ 1..999 | Контракт — по DTO, не по угадыванию |
| `SedUser` без `fullPostName`, `active`, `postId`, `meIo`, `secretaries`, `griefIds`, `views`, `widgets`, `scanWia` | Все они есть в `CurrentUser.java` | **Не** тащить весь DTO (см. 2.1) — но не выдумывать «урезанный, зато неверный» |
| «OWASP **LLM01:2026**» | В проекте зафиксирован **OWASP Top 10:2025** (A01–A10, план hardening §1). Версия LLM-топа не подтверждена | Не ссылаться на год; для виджета актуальны **XSS из вывода модели** и утечка токена (2.8) |
| `--spring-default: 0.4s cubic-bezier(…)` как «spring preset» | cubic-bezier **не является** spring'ом | Spring в CSS выражается `linear(...)` (аппроксимация); настоящий spring — только JS. Виджету он не нужен → CSS-пресет убрать |
| «Lighthouse accessibility ≥ 95» | Lighthouse считает **host-страницу**, Shadow DOM он видит частично | Гейт ставить по `standalone.html`, зафиксировать что именно меряется (4.1) |

### 1.2. Верно, но недооценено (черновик прав — усилить)

- `localStorage` в `ChatShell`: `palatium.thread_id`, `palatium.user_id`, `palatium.org_id` — верно.
- `sessionStorage` для токена (`palatium.access_token`) и trace-id (`palatium.trace_id`) — верно.
- Токен WS в query-string (`/ws/sessions/{thread}?token=…`) — верно.
- `manualChunks {vendor, ui, animations}`, `cssCodeSplit: true`, `minify: 'esbuild'`, `target: 'es2020'` — верно.
- `TokenIcon`: lottie для `success/warning/danger/info`, lucide для остального — верно (плюс `check` → `successAnim`).
- Ключи motions: `dotPulse`, `spin`, `fadeSlide`, `pulse`; нет `prefers-reduced-motion`, нет `--ease-*`/`--duration-*` — верно.
- Google Fonts (Fraunces + IBM Plex) в `index.html` — верно; для СЭД это **недопустимо** (2.6).
- `BlockRenderer`/`BlockView` мемоизированы; `BlockRenderer` рисует **только текстовые узлы**, `dangerouslySetInnerHTML`/`innerHTML` — 0 совпадений; `widget.href` прогоняется через `safeHttpHref` (только `http/https`) — **это надо сохранить и защитить тестом** (2.8).

### 1.3. Пропущено черновиком (добавлено в план)

| Что | Где | Почему важно |
|---|---|---|
| `startNewThread()` делает `window.localStorage.setItem` + `window.location.reload()` | `ChatShell.tsx` | Виджет **не может перезагружать страницу СЭД** — это блокер embed'а, а не «мелочь» |
| Хардкод строк смешан (UI — EN, ошибки `client.ts` — RU) | `web/src/**` | i18n — не «добавить слой», а сначала **извлечь строки**; объём работы недооценён |
| Нет ни одной тестовой инфраструктуры во `web/` | `web/package.json` scripts = `dev/build/preview` | Нельзя писать E2E «поверх» — сначала W4/W1-гейты |
| Нет `web/packages/*`, нет `workspaces` | `web/package.json` | «Пакет `@palatium/contract`» требует workspace + TS project references |
| `expressCem`/CEM-анализатор не подключён | — | CEM — это W1, а не «сгенерировать» |
| СЭД не хранит `me` в Redux — читает из `sessionStorage` на каждый запрос | `fetchAuth.js` (`getMe`) | Хост отдаёт контекст из storage/`getMe()` — handshake должен уметь «дай текущий контекст», а не только «я изменился» |

---

### 1.4. Вердикт по расширенной инструкции (Фазы 1–4)

Инструкция — правильная **по направлению** (аудит → дизайн → план → чеклист, capability whitelist, tenancy, scope-RAG, HITL, «токен только в памяти»), но содержит проверяемо неверные факты и **прямые конфликты с действующими правилами**. Ниже — построчно; «верно → делаем», «неверно → правим», «конфликт → нельзя в таком виде».

**✅ Подтверждено кодом (берём без изменений)**

| Утверждение | Доказательство |
|---|---|
| `authorities` — атомарные разрешения; примеры реальны | `Permission.java` (security/model): `CREATE_SYNCHRONIZATION_TASK_SAP` (:55), `CREATE_ACCESS_GRIEF` (:90), `CREATE_ACCESS_GRIEF`… `DELETE_WORK_CALENDAR` (:125), `CREATE_COUNTRY` (:235). Всего ≈302 константы |
| `roles` — UUID-набор | `CurrentUser.getRoles(): Set<UUID>` |
| Поля профиля (`orgId`, `departmentId`, `departmentName`, `post`, `postId`, `country`, `localization`, `fired`, `archivist`, `griefIds`, `meIo`, `settings`, `responsibleNomenclatureDepartmentIds`, `subordinatesDepartments`) | `CurrentUser.java` — все присутствуют (+ `views`, `widgets`, `scanWia`, `docEllipsis`, `showEventDesign`, `active`) |
| `country: { alphaCodeTwo, alphaCodeThree, code }` | `CountryDto` (code ∈ 1..999) |
| Токен — только в памяти; никакого storage | совпадает с 1.2/2.5 |
| Multi-tenant по `orgId` как tenant | бэкенд уже несёт `org_id` (memory namespaces, `principal.org_id`) |

**❌ Фактически неверно (правим)**

| Утверждение | Факт |
|---|---|
| «React 18 или 19? обосновать миграцию» | `web/package.json`: `react ^19.1.1` — миграция **не нужна** |
| «СЭД: Redux Toolkit (RTK Query), множество API-слайсов» | в референсе `frontend/gtb`: **plain `redux ^4.0.5` + `react-redux ^7` + `redux-thunk` + `redux-devtools-extension`**, React **17**, `react-router-dom ^5`. `@reduxjs/toolkit`/`createSlice`/RTK `createApi` — **0 совпадений** (найденные `createApi=` — пропсы форм) |
| «объект `mi`» | в референсе ключ — `me` (`SESSION_STORAGE_ME_NAME = 'me'`, `getMe()`); `mi` не встречается |
| «WebSocket `/ws/chat`» | в проекте `/ws/sessions/{thread_id}` (`presentation/websockets/session.py`), JWT из `?token=` или `Authorization` |
| «Rate limiting — gap» | **есть**: `RateLimitMiddleware` (`presentation/middleware/rate_limit.py`, настроен в `app.py` с `security.api_rate_limit`) |
| `post.name` | `PostDto.postName` (уже исправлено в §1.1) |
| «MCP 2026-07-28: stateless core + OAuth 2.0 + OIDC» как требование | канон проекта — JWT `aud=mcp:<server>` (`mcp-roadmap.md`, Track A Phase 3, DONE). OAuth2/OIDC — смена уже принятого решения, отдельный трек |
| «Neo4j Browser как эталон: `plgAssistant.systemPrompt`, `agentChat.visible`, `kgBuilder`» | **не проверяемо** в этом репо; это не JavaEdms. `verify` — не проектировать по этому |
| «BM25 + dense + RRF» | проект: Postgres FTS `ts_rank_cd` (`postgres_memory_port.py:312`) + pgvector-косинус + опциональный **embedding rerank** (`embedding_rerank.py`). 060 **прямо запрещает** называть это «BM25»; RRF не используется |
| «cross-encoder реранкер», «recall@5 > 0.8, groundedness > 0.9» | новая модель + новый eval-гейт; сегодня rerank — косинус по лексическим кандидатам. Числа — цель, не факт |
| «namespace `tenant_114_documents`» + `$or`-фильтр (Mongo-синтаксис) | проект — Postgres/pgvector + **RLS `FORCE ROW LEVEL SECURITY`** + обязательный tenant-scope (`assert_tenant_scoped_cypher`, `$tenant_param`). 060: «Отсутствие политики RLS в миграции — ошибка ревью» |
| «OWASP LLM01:**2026**» | непроверенная версия. Зафиксированная база — OWASP Top 10:**2025**; для LLM корректна ссылка на **LLM Top 10 2025** (LLM01:2025 Prompt Injection). Год не хардкодить |
| «Declarative Shadow DOM решил проблему SSR» | SSR в этом виджете **вне scope** (2.1/§0) — DSD здесь не нужен |
| «lazy loading markdown renderer и syntax highlighter» + IIFE single-file | несовместимо (2.4), и этих компонентов в проекте **нет** (код рисуется `<pre><code>`) |

**Решение по расхождению:** пользователь подтвердил (2026-09-29) — истина именно `gtb` (React 17, plain Redux, `me`). Вариант `mi` + Redux Toolkit/RTK Query отброшен: контракт и интеграцию проектировать по `gtb`.

**⛔ Конфликт с правилами (в предложенном виде нельзя)**

| Предложение инструкции | Правило | Как правильно |
|---|---|---|
| MCP-серверы `sed-documents`, `sed-tasks`, `sed-workflow`, `sed-users` | 070 + `mcp-roadmap.md`: канон серверов — `{platform, edms, analytics}` | Расширять существующий `edms` через правку перечня 070 + RBAC-обсуждение |
| `BASE_TOOLS = search_knowledge_base, ask_clarification, cite_source` | 070: закрытый перечень назван иначе (`search_knowledge`, `search_memory`, `save_memory`, `forget_memory`, `extract_transcript_memories`, `ingest_document`, `graph_query`, `web_fallback`) | Использовать канонические имена; новое имя = правка 070 |
| `validate_tool_call(...) raise PermissionError(...)` | **070.3**: отказ RBAC — не исключение наружу | Типизированный результат отказа → `AgentOutput(status="failure")` + audit `permission_denied` + метрика `palatium_rbac_denied_total` |
| `audit_log.warning(f"...authorities {user_authorities}")` | 040/020: логи только через structlog, без payload | Логировать `trace_id` + имя tool + решение, без дампа authorities |
| Проверка прав «middleware на бэке» рядом с Harness | 070.2: `ToolExecutor` — **единственная** точка RBAC | Проверка внутри `ToolExecutor`, Harness не дублирует |
| `fired: true → ассистент не запускается` (как UI-правило) | 020: guardrails в коде, не в UI | Серверная проверка на каждом запросе; виджет — только UX |
| `archivist: true → только read-only` (как флаг UI) | 020/070: RBAC-профиль инструментов — на сервере | Серверный allow-list (read-only) + проверка в `ToolExecutor` |
| Создать `AUDIT.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CHECKLIST.md` в корне | 050: дублирование; `ROADMAP` уже есть (этот файл) | Audit/Architecture — в `docs/` (docs-as-code, 086); Roadmap — только здесь; Checklist — заменить гейтами (4.3) |

**⚠️ Реальные пробелы (в инструкции их нет — добавляем в план)**

1. **`roles` UUID → имена упирается в права:** `GET /api/role/all` требует `READ_ROLE` (`RoleController.java:67-77`). Обычный пользователь без `READ_ROLE` список ролей **не получит** → нужен источник (host/отдельный read-only эндпоинт) или отказаться от имён.
2. **Кеш** названий ролей «в памяти сессии» — 050 запрещает кеш без лимита/TTL/инвалидации; плюс риск кросс-tenant утечки при глобальном кеше.
3. **Аудит в СЭД:** аудит Palatium (hash-chained) ≠ аудит СЭД. Запись действий ассистента в аудит СЭД — новая интеграционная задача без контракта (вопрос §5).
4. **Стриминга токенов сегодня нет:** WS отдаёт только `session.subscribed`/`pong`/`error`; ходы идут через HTTP `POST /intents/process`. `chunk`/`tool_call`/`citation`/`done`/`error` — проектировать с нуля (WS-события vs SSE — решение).
5. **Capability whitelist отсутствует.** Генерировать маппинг authority→tools **из enum `Permission`** (≈302), а не выписывать руками; иначе дрейф.
6. **`gen_ai.conversation.id`** — сверить с уже существующими именами в `core/observability` (040), не вводить второй набор.

### 1.5. Что в инструкции сделано лучше первого черновика

- Capability whitelist из `authorities` — правильная идея (наследовать права, не дублировать RBAC).
- Scope-RAG по `departmentId`/`subordinatesDepartments`/`responsibleNomenclatureDepartmentIds` — соответствует данным СЭД.
- `fired`/`archivist` — нужные гейты (с поправкой на серверную реализацию).
- Явный handshake «СЭД → контекст, ассистент → действия», BFF как **целевая** архитектура, audit-лог действий.
- Корректный запрет localStorage/sessionStorage/cookie для токена — жёстко и верно.

---

## 2. Контракт и архитектура (исправленное ядро)

### 2.1. `@palatium/contract` — минимальный, не зеркало `CurrentUser`

Пакет: `web/packages/contract/` + `"workspaces": ["packages/*"]` в `web/package.json` (корень репо — Python, npm-root = `web/`). Сборка: ESM + CJS + `.d.ts`; TS `composite: true` + `references` из `web/tsconfig.json`.

Правило: контракт содержит **только то, что виджет реально читает**. Копия всего `CurrentUser` свяжет виджет с внутренней моделью СЭД и будет дрейфовать (050, YAGNI).

```typescript
// web/packages/contract/src/index.ts
export type SedLocalization = 'RU' | 'EN' | 'GE'; // enum JavaEdms; маппинг → BCP-47 см. 2.6

export interface SedUser {
  id: string;              // UUID
  orgId: string;           // tenant
  departmentId?: string;
  departmentName?: string;
  fullName?: string;       // display-значение, вычисляет host
  localization?: SedLocalization;
  active?: boolean;
  fired?: boolean;
}

export interface SedPermissions {
  authorities: readonly string[];  // GrantedAuthority → capability whitelist
  roles: readonly string[];        // Set<UUID>
  responsibleNomenclatureDepartmentIds?: readonly string[];
  subordinatesDepartments?: readonly string[];
  archivist?: boolean;
}

export interface SedDocumentRef {
  id: string;
  type?: string;
  departmentId?: string;
}

export interface SedContext {
  token: string;                   // короткоживущий; только в памяти виджета
  user: SedUser;
  permissions?: SedPermissions;
  document?: SedDocumentRef;       // открытый документ — контекст запроса
  scope: { tenantId: string; departmentIds: readonly string[] };
  settings?: Record<string, unknown>; // widgets / docEllipsis / showEventDesign — как есть
  threadId?: string;                  // тред, который host уже ведёт (1…128, `normalizeThreadId`)
}

export const SED_EVENTS = {
  CONTEXT_CHANGED: 'sed:context-changed',
  CONTEXT_REQUESTED: 'sed:assistant-context-requested', // виджет → host (handshake, 2.2)
  TOKEN_REFRESHED: 'sed:auth-token-refreshed',
  TOKEN_REQUESTED: 'sed:auth-token-requested',         // виджет → host
  THREAD_CHANGED: 'sed:thread-changed',                // виджет → host (host сохраняет id → SedContext.threadId)
  ACTION_REQUESTED: 'sed:action-requested',            // виджет → host (irreversible → HITL на бэке)
  ASSISTANT_READY: 'palatium:ready',
} as const;
```

Изменение любого поля/события здесь = правка контракта обеих команд (005), а не локальный PR.

### 2.2. Handshake контекста (исправление главного бага черновика)

Черновик: «если `sed:context-changed` не пришёл за 500 ms → standalone». Это лечит **таймаут**, но не **гонку**: СЭД может отправить контекст **до** апгрейда кастомного элемента (`customElements.define` ещё не выполнен) — событие потеряно, и виджет уйдёт в standalone навсегда.

Правильно — двусторонний handshake:

1. `connectedCallback` → виджет dispatch `sed:assistant-context-requested` (на `window`, `composed: true`).
2. Host либо вызывает `el.setContext(ctx)`, либо dispatch `sed:context-changed` (на элемент или `window`).
3. Виджет слушает **и** `window`, **и** собственный элемент; принимает контекст, если `token` и `user.id` непустые.
4. Только после того как запрос отправлен и прошёл `CONTEXT_TIMEOUT_MS` (500 ms) **без ответа** → standalone-режим.
5. Обновления (`sed:context-changed` при смене документа/пользователя) — идемпотентны и не требуют перезагрузки.

Дополнительно: поддержать `window.__palatiumSedContext` (host может выставить **до** загрузки скрипта) — читается один раз на connect. Это снимает гонку полностью.

### 2.3. Web Component — исправленные дефекты черновика

```typescript
// web/src/widget.tsx (эскиз; ЯВНЫЕ исправления помечены)
class PalatiumAssistant extends HTMLElement {
  static get observedAttributes() { return ['lang', 'density']; } // 'position' — не нужен без layout-логики

  #root: Root | null = null;           // ИСПРАВЛЕНО: root живёт между connect/disconnect
  readonly #shadow: ShadowRoot;
  readonly #mount: HTMLDivElement;
  #bridge: HostContextBridge;

  constructor() {
    super();
    this.#shadow = this.attachShadow({ mode: 'open' });
    // ИСПРАВЛЕНО: adoptedStyleSheets вместо <style> — CSP и производительность (2.8)
    const sheet = new CSSStyleSheet();
    sheet.replaceSync(cssText);
    this.#shadow.adoptedStyleSheets = [sheet];
    this.#mount = document.createElement('div');
    this.#mount.id = 'palatium-root';
    this.#shadow.append(this.#mount);
  }

  connectedCallback() {
    // ИСПРАВЛЕНО: создаём root один раз, переиспользуем при reconnect
    this.#root ??= createRoot(this.#mount);
    this.#render();
    this.#bridge.requestContext();                    // 2.2, шаг 1
    this.dispatchEvent(new CustomEvent(SED_EVENTS.ASSISTANT_READY, { bubbles: true, composed: true }));
  }

  disconnectedCallback() { /* ИСПРАВЛЕНО: НЕ unmount — виджет может быть перемещён в DOM */ }

  attributeChangedCallback() { this.#render(); }      // ИСПРАВЛЕНО: без него observedAttributes бесполезны

  setContext(ctx: SedContext) { this.#bridge.apply(ctx); }  // ИСПРАВЛЕНО: напрямую, без фантомного 'palatium:context-set'
  open() / close() { /* state виджета, не события наружу */ }
}
customElements.define('palatium-assistant', PalatiumAssistant); // host гарантирует уникальность
```

Что ещё исправлено относительно черновика:

| Дефект черновика | Почему ломается | Исправление |
|---|---|---|
| `disconnectedCallback` → `root.unmount(); root = null` | Перемещение элемента в DOM (СЭД перерисует layout) → пустой виджет навсегда | root не уничтожать; `unmount` только по явному `destroy()` |
| `observedAttributes` без `attributeChangedCallback` | Атрибуты объявлены, но игнорируются | добавить |
| `setContext()` диспатчит `palatium:context-set`, который никто не слушает | Публичный API — no-op | писать в bridge напрямую |
| `palatium:ready` из `connectedCallback` | При reconnect летит повторно | idempotent: один раз на connect, с `context-requested` |
| `static get observedAttributes → 'position'` | Нет layout-логики, которая бы его читала | убрать (YAGNI) |

### 2.4. Сборка — выбор bundle-стратегии (главное противоречие черновика)

Черновик одновременно требует `formats: ['iife']`, `inlineDynamicImports: true` **и** lazy-load (`lottie-web`, markdown, подсветку). Это взаимоисключающие требования: single-file IIFE **не может** code-split'иться.

Решение (дефолт плана, проверить измерением на W1):

- **Базовый артефакт — single-file IIFE.** СЭД подключает один `<script>` + один тег. Lazy-load тяжёлых библиотек **исключается**; бюджет держим тем, что `lottie` уже тонкий (4 маленьких JSON) и markdown-рендерера в проекте **нет** (код рисуется как plain `<pre><code>`).
- **Если бюджет пробит** — второй артефакт ESM (`formats: ['es']`) с `base` по абсолютному CDN-URL и динамическим `import()`; переключение — по факту замера, а не заранее.

```typescript
// web/vite.config.wc.ts
export default defineConfig({
  plugins: [react({ jsxRuntime: 'automatic' })],
  define: { 'process.env.NODE_ENV': '"production"' },
  build: {
    lib: { entry: 'src/widget.tsx', name: 'PalatiumAssistant', formats: ['iife'],
           fileName: () => `palatium-assistant.v${version}.[hash].iife.js` },   // semver + контент-хеш (W7)
    rollupOptions: { output: { inlineDynamicImports: true, assetFileNames: 'palatium-assistant.[ext]' } },
    cssCodeSplit: false,      // moot при `?inline`, оставлено для ясности
    minify: 'esbuild', target: 'es2022', sourcemap: false,
  },
  esbuild: { legalComments: 'none' },
});
```

Уточнения, которых нет в черновике:
- `manualChunks` в lib-режиме **нельзя** — не переносить из `vite.config.ts`.
- `target: es2022` здесь **осознанно отличается** от `es2020` app-сборки (СЭД = Chromium Edge) — зафиксировать комментарием.
- `?inline` сохраняет `url()` внутри CSS → шрифты/ассеты должны быть либо заинлайнены (`assetsInlineLimit`), либо быть system stack, иначе «single-file» ложь (2.6).
- `assetsInlineLimit` и `base` — часть контракта доставки; без абсолютного `base` ESM-вариант не найдёт чанки.

### 2.5. Auth — исправленный контракт черновика

```typescript
// web/src/api/client.ts
let inMemoryToken: string | null = null;
let mode: 'host' | 'standalone' = 'standalone';

export function setToken(token: string): void { inMemoryToken = token; }
export function setMode(next: 'host' | 'standalone'): void { mode = next; }
// refresh — только через host; dev-token mint разрешён ТОЛЬКО в standalone
```

- `mintDevToken` (`/auth/dev-token`) вызывается **только** в `mode === 'standalone'`. В embed попытка сминтить токен = ошибка, а не тихий fallback.
- 401 → `sed:auth-token-requested` → host отвечает `sed:auth-token-refreshed` → запрос повторяется **один раз**.
- Убрать: `writeStoredToken`/`readStoredToken`, `TOKEN_STORAGE_KEY`, `sessionStorage` в `trace.ts` (trace-id — в памяти модуля), `localStorage` в `resolveThreadId/UserId/OrgId`.
- `startNewThread()` **не** делает `window.location.reload()` (2.1.3/1.3) — сброс состояния React + опциональный `sed:action-requested` хосту.
- `userId`/`orgId` для API берутся из `SedContext` (`user.id`, `scope.tenantId`), а не из storage. `thread_id`: в embed — из атрибута/контекста либо in-memory (§5 п.5).
- WS: `token` в query-string сохраняется (совместимость с бэком — вне scope), но host-origin СЭД должен быть разрешён (4.2).

### 2.6. Темизация, шрифты, Shadow DOM

- **Шрифты:** `index.html` тянет Google Fonts — в СЭД это запрещено (внешний запрос из чужого приложения + приватность). Варианты: system stack (`system-ui`) или self-hosted `@font-face` внутри Shadow DOM. `fonts.googleapis.com` в виджете — дефект.
- **Темизация:** сейчас `styles.css` — только `color-scheme: dark`. СЭД светлая (Bootstrap). Добавить `:host { … }` + CSS custom properties, которые host может переопределить через атрибуты/`::part()`. `::part()` — точечный публичный API; не отдавать наружу весь интерьер.
- **Плотность/язык** — атрибуты `density` / `lang` (2.3).
- Расширить `:host` до `[data-theme="light|dark"]`, уважать `prefers-color-scheme`.

### 2.7. Motion — исправления

- Токены (`--ease-out`, `--ease-in-out`, `--ease-drawer`, `--duration-*`) — **взять как в скилле**, они совпадают с `animate`/`emil-design-eng`/`apple-design`.
- **Убрать** `--spring-default` из черновика. Если форма кривой нужна — `linear(...)`; настоящих spring'ов в виджете не требуется.
- Существующий `.action-btn:active { transform: scale(0.9) }` → `scale(0.97)`, `120ms var(--ease-out)`.
- `.send-btn:hover { transform: scale(1.02) }` — обернуть в `@media (hover: hover) and (pointer: fine)` (сейчас hover не гейтится → ложные hover на touch).
- `prefers-reduced-motion`: черновик предлагает глобальный нюк `animation-duration: 0.01ms !important` — это убьёт `spin` и `dotPulse`, которые являются **индикаторами статуса**, а не декором. Скилл прямо говорит: reduced motion — «мягче, не ноль». Скоупить: убрать `transform`-движение, сохранить opacity/color/статус-лоадеры.
- Stagger для `.hitl-stack > .hitl-card` (30–80 ms) — ок, класс существует.
- Tabs-индикатор через `clip-path` — **опционально** и только если реально появится анимированный таб-индикатор (сейчас такого компонента нет → YAGNI, не тащить в W5).
- Единственные `@keyframes` в проекте (`fadeSlide`, `dotPulse`, `spin`, `pulse`) не «быстро-триггерные» — оставить; проверить, что ни один не триггерится на каждый keystroke.

### 2.8. Security (frontend-периметр)

| Риск | Текущее состояние | Требование |
|---|---|---|
| XSS из вывода модели | Безопасно: `BlockRenderer` — только текст, без `dangerouslySetInnerHTML`; `safeHttpHref` пропускает лишь `http/https` | Зафиксировать **regression-тестом** и правилом 084: никакого raw HTML в блоках; новые типы блоков — ревью на инъекцию |
| Утечка токена | `sessionStorage` — исправить (2.5) | Только память; grep-гейт (4.1) |
| Untrusted content (web_fallback) | В бэке есть `domain/policies/untrusted_content.py` | Виджет обязан **визуально маркировать** внешний источник; контракт пометки — согласовать, не выдумывать (§5 п.7) |
| CSP | Host-страница СЭД имеет свою политику | Виджет принимает `csp-nonce`; предпочесть constructed `CSSStyleSheet` (`adoptedStyleSheets`) — но применимость к `style-src` **пометить `verify`** по целевым браузерам |
| Supply chain | — | SRI (`integrity`) на бандл, immutable cache по хешу в имени, semver (4.1) |
| Clickjacking | — | Виджет — скрипт, не iframe; `frame-ancestors` не про него. Не вводить iframe-доставку |
| CSRF / BFF | Сегодня — bearer-токен напрямую; `credentials: 'include'` в черновике **не** используется | BFF — **целевая** архитектура (ADR, 086). Сегодняшний дизайн не притворяется BFF'ом |

Dev-time `permissions.json`/`mcpAllowlist` (правило 020) к виджету **не относятся** — не смешивать слои.

---

### 2.9. Backend: что уже есть (не перепридумывать) и что реально менять

Прежде чем проектировать «по 2026», сверить с фактом — половина предложений инструкции уже реализована иначе.

| Слой | Уже есть (факт) | Что предлагала инструкция | Вердикт |
|---|---|---|---|
| Оркестрация | LangGraph, `application/orchestration/` (000/065) | «LangGraph **или** Pydantic AI» | Оставить LangGraph; смена фреймворка — не этот трек |
| MCP | канон `{platform, edms, analytics}`; platform — Host-local discovery + handler | 4 сервера `sed-*` | Расширять `edms` правкой 070 |
| Инструменты | закрытый перечень 070 (8 имён) | другие имена + `BASE_TOOLS` | Привести к 070 |
| RBAC | `PlatformToolPin` + `ToolExecutor.try_execute` + `allowed_tools`; отказ — типизированный результат (070.3) | middleware + `raise PermissionError` | Переделать под 070.3 |
| Capability whitelist | **нет** (W10a: генератор authority готов) | есть проект маппинга | **Взять** — генерировать из enum `Permission`; привязка tool→authority по согласованию (§5 п.16) |
| Поиск | FTS `ts_rank_cd` + pgvector-косинус + `EmbeddingRerankMemoryPort` | BM25 + RRF + cross-encoder | Оставить; cross-encoder — отдельное решение (060: «BM25» — неверный термин) |
| Tenant-изоляция | RLS `FORCE` (`attachments`), tenant-scope `$tenant_param` для `graph_query`, org-namespaces памяти | namespace `tenant_114_*` | Оставить RLS+scope; namespace — другая модель |
| Стриминг | `POST /intents/process` (HTTP); WS `/ws/sessions/{thread_id}` — только events/keepalive | WS `/ws/chat` с `chunk/tool_call/citation` | **Gap:** токен-стриминг + citations проектировать (путь и протокол — решение) |
| Rate limit | `RateLimitMiddleware` | «добавить» | Уже есть; для tenant-квот — расширение |
| Audit | hash-chained audit + `permission_denied` события (040) | audit-лог действий | Есть; «запись в аудит СЭД» — новая задача |
| Observability | OTel-трейсы + метрики реестра (040) | `gen_ai.conversation.id` | Сверить с существующими именами, не плодить второй набор |
| Вложения | scan→parse→injection gate, presigned upload, RLS | — | Уже есть; пререквизит — сеть СЭД (4.2) |

**Итог:** Track II — это **четыре точечные доработки**, а не «перепроектировать бэкенд»: capability whitelist из `Permission`, scope-фильтры поиска, персонализация/гейты (`fired`/`archivist`), стриминг+citations. Всё остальное уже соответствует «2026» и защищено правилами.

---

## 3. Волны — Track I (виджет)

Каждая волна мержится отдельно, не расширяет scope. Порядок — по риску.

### W0 — Контракт и baseline — ✅ DONE

- `web/packages/contract/` (типы 2.1, `SED_EVENTS`, `isSedContext`, `toBcp47`, `buildDepartmentScope`), `workspaces: ["packages/*"]` в `web/package.json`, `include: packages/contract/src` в `web/tsconfig.json`.
- Пакет **source-first** (`exports` → `src/index.ts`), без `composite`/`references` и без сборки ESM+CJS+`d.ts` — обоснование в «Статус реализации», п.1.
- `web/standalone.html` + мок-хост (контекст и по запросу, и до апгрейда элемента).
- **DoD:** `npm run typecheck` зелёный (виджет + контракт); Vite резолвит `@palatium/contract` (проверено в dev: `/packages/contract/src/index.ts`); `standalone.html` отдаётся 200.

### W1 — Web Component + Shadow DOM + сборка — ✅ DONE

- `web/src/widget.tsx` (2.3: root переживает reconnect, `attributeChangedCallback`, `setContext` без фантомных событий, `open`/`close` через `[collapsed]`), `web/vite.config.wc.ts` (2.4), CSS через `?inline` + `adoptedStyleSheets` (одна `CSSStyleSheet` на все экземпляры).
- Токены вынесены в `web/src/tokens.css` (`:root, :host`) — иначе в shadow root переменные не резолвятся.
- Замер: **460.33 kB raw / 140.43 kB gzip** (бюджет < 150 KB соблюдён) → ESM-вариант не нужен, см. 2.4.
- `custom-elements.json` — `@custom-elements-manifest/analyzer` (`npm run cem`, конфиг `web/custom-elements-manifest.config.mjs`);
  в манифесте: `tagName`, `lang`/`collapsed`, `palatium:ready` (из `@fires`), шесть `::part()`, `@cssprop`. Поле `customElements`
  в `web/package.json` уже указывало на файл — IDE/тулинги подхватят без настройки.
- **DoD:** `<palatium-assistant>` собирается в single-file IIFE (один бандл, имя — `palatium-assistant.v<semver>.<hash>.iife.js`, W7);
  `attachShadow`/`adoptedStyleSheets`/CSS-токены присутствуют в бандле; `eval` не тянется; `custom-elements.json` валиден и содержит контракт элемента.

### W2 — Event bridge + handshake — ✅ DONE (кроме `ACTION_REQUESTED`)

- `web/src/lib/hostContext.ts`: `CONTEXT_CHANGED`, `TOKEN_REFRESHED` (слушаем `window` **и** элемент), `CONTEXT_REQUESTED`, `window.__palatiumSedContext`, окно 500 мс → `markStandalone()`.
- `ChatShell` больше не читает storage: контекст приходит из `useAssistantRuntime()` (`user.id`, `scope.tenantId`), бейдж `standalone` в шапке показывает режим.
- ⏳ `sed:action-requested`: **не реализован** намеренно. Эмитить событие без потребителя — мёртвый код. Каталог
  закрыт в W9 (`AssistantAction`: `open_document`/`navigate`/`search`, ключи разделов — из `route.js` СЭД);
  включение эмиссии — вместе с обработчиком на стороне СЭД (§8.2 `docs/embedded-assistant.md`).
- **DoD:** контекст dispatch до/после `palatium:ready` — обе ветки ведут в `applyHostContext`; без контекста `hostStatus → standalone` через 500 мс; `setContext()` валидирует payload (`isSedContext`) и бросает на мусоре.

### W3 — Auth без storage — ✅ DONE

- `client.ts`: токен в `runtime/auth.ts` (память), 401 → `sed:auth-token-requested` → ровно один retry; `mintDevToken` бросает в host-режиме; `trace.ts` — id в памяти (+ лимит длины заголовка); `ChatShell.startNewThread` без `location.reload()`.
- **DoD:** grep по `web/src` — совпадения `localStorage|sessionStorage|document.cookie|location.reload` только в комментариях; бандл не содержит `localStorage`/`sessionStorage`/`location.reload`.

### W4 — Темизация, шрифты, публичный API стилей — ✅ DONE (палитра light сверена в W8)

- `web/src/tokens.css`: светлая тема на `:root[data-theme='light'], :host([data-theme='light'])` + `color-scheme` переключается вместе с темой.
  **Opt-in, не `prefers-color-scheme`** — обоснование в отклонении 6. Google Fonts убраны из `index.html`; `--font-sans` — system-стек
  (`Inter` остаётся первым: если хост загрузил его сам, типографика подхватится без наших запросов).
- `web/src/widget.css`: `:host` получил то, что в приложении задавалось на `html/body` (фон, градиенты, типографика), + нейтрализация
  `text-align`/`letter-spacing`/`font-size` хоста — СЭД на Bootstrap иначе «протекал» бы в виджет.
- Публичный API: шесть частей (`launcher`, `shell`, `header`, `transcript`, `composer`, `close`) и лончер, который показывается в
  свёрнутом состоянии. Состояние панели — в runtime-store (`panelOpen`), атрибут `[collapsed]` на хосте — зеркало для CSS хоста и
  внешнего кода; `close()` не размонтирует чат (иначе терялись бы история и открытые HITL-карточки).
- `web/standalone.html`: кнопки `Свернуть: close()` / `Развернуть: open()`, переключатель `data-theme`, демо `::part(launcher)`
  и `::part(header)` — стенд показывает оба рычага (токены и части).
- **DoD:** переопределение темы хостом работает без правок виджета; внешних сетевых запросов за шрифтами нет (grep по `fonts.googleapis` — 0);
  `::part()` присутствуют в бандле. Визуальная сверка светлой палитры выполнена в W8 (axe-контраст + кадры `npm run test:shots`);
  «виджет на светлом Bootstrap-фоне» остаётся за реальным СЭД-стендом (W9) — на стенде этот фон не воспроизводится.

### W5 — Motion-токены и полировка — ✅ DONE

- `web/src/tokens.css`: `--ease-out`/`--ease-in-out`/`--ease-drawer` + `--duration-press…drawer`; из черновика `--spring-default`
  **не перенесён** (cubic-bezier — не spring).
- `web/src/styles.css`: все 8 hover-правил под `@media (hover: hover) and (pointer: fine)` (ложный hover на тач-экране),
  `.action-btn:active` → `scale(0.97)` 120 ms, stagger `.hitl-stack > .hitl-card` (40/80/120 ms, ограничен 4-й карточкой),
  `.msg` и stagger переведены на токены, добавлен `.action-card.action-choice:active`.
- `prefers-reduced-motion` **скопирован, не глобальный нюк**: гасятся появление и `transform`-отклик, сохраняются `.spin`
  и `.typing-dots` (индикаторы статуса: без них «работаю» неотличимо от «зависло»).
- **DoD:** `transition: all` — 0 · `scale(0)` — 0 · `ease-in` на UI — 0 · hover без гейта — 0 · `prefers-reduced-motion` присутствует
  и не содержит `animation-duration: 0.01ms !important` ✅ (grep). Slow-motion в DevTools не проверялся — в W8 заменён
  детерминированным тестом `prefers-reduced-motion` (гаснет появление, остаётся индикатор работы).

### W6 — i18n — ✅ DONE (RU/EN; `GE` — закрыто §5 п.3)

- `web/src/i18n/messages.ts` — ключи объявлены один раз в `ru`, английский типизирован как `Record<MessageKey, string>`,
  поэтому пропущенный перевод = ошибка компиляции, а не русская строка в англоязычном UI. 109 ключей: шапка, лончер, пустое состояние,
  действия над ответом, композер, уведомления, отказы вложений, ошибки клиента.
- `web/src/i18n/index.ts` — `t(key, params)`, подстановка `{param}`, числа и даты — `formatNumber` / `formatDateTime`
  по локали интерфейса. Модуль **не импортирует**
  `runtime/store` (иначе цикл `store → auth → i18n → store`): локаль в него **пушит** store при публикации, поэтому `t()` работает
  и вне React (`client.ts`, `attachments.ts`, `auth.ts`).
- Локали **статические** (отклонение 5). `RU|EN|GE` → BCP-47: `toBcp47` уже в контракте. Для `GE` ресурсов нет и у самого СЭД
  (`frontend/gtb/src/i18n.js`, `fallbackLng` = RU), поэтому `toBcp47('GE')` → `null`, а runtime при наличии контекста берёт
  язык host'а, а не браузера — закрыто в W9 (§5 п.3).
- **DoD:** хардкод-строк в отгружаемом UI нет (проверено чтением `ChatShell`/`client.ts`/`attachments.ts`/`auth.ts`) — ⚠️ **энфорсмент
  отложен**: ESLint во `web/` нет, гейт «нет хардкод-строк» остаётся за правилом `084` (W4 плана hardening). Переключение языка
  вживую покрыто в W8 (`host.spec.ts`: атрибут `lang` → интерфейс на английском без перезагрузки и без потери диалога).

### W7 — Доставка и публикация — ✅ DONE

- **Имя артефакта:** `palatium-assistant.v<semver>.<hash>.iife.js` — версия из `package.json` (в `vite.config.wc.ts`),
  хеш от Rollup. Контент-хеш делает файл иммутабельным: обновление меняет URL, поэтому `Cache-Control: immutable` безопасен.
- **`web/scripts/widget-release.mjs`** — один проход после `vite build`: SRI `sha384`, размеры (raw/gzip), бюджет,
  валидация CEM, копия манифеста в артефакт, запись `release.json` (версия, файл, дайджест, `cacheControl`).
  Режим `--verify` сверяет дайджест и размер с файлом + версию с `package.json`.
- **Гейт бюджета:** сборка падает при gzip > 150 KiB; число меряется тем же уровнем сжатия, что печатает `vite build`
  (иначе отчёт и бюджет жили бы в двух мирах: level 9 даёт −380 байт).
- **CI:** job `frontend` — `npm ci` → `typecheck` → `cem:check` → `build:widget` → `verify:widget` → артефакт
  `palatium-assistant-widget` (бандл + `release.json` + `custom-elements.json`). Node 22, кэш npm по `web/package-lock.json`.
- **`.gitattributes`:** `web/** text eol=lf`. Не стилистика: CEM встраивает JSDoc из `widget.tsx` дословно вместе с
  переводами строк, поэтому при `core.autocrlf=true` (включён на этой машине) регенерация манифеста давала другие байты
  и гейт `cem:check` падал бы локально при зелёном CI. По ходу работы 16 файлов frontend'а были приведены к LF.
- **DoD:** артефакт собирается из CI; `integrity` совпадает с файлом; CEM в артефакте; semver+hash в имени (2.4/4.1).
  Проверено: подмена байта бандла → `verify` падает (exit 1); бюджет 100 KiB → сборка падает (exit 1);
  дрейф JSDoc в `widget.tsx` → `cem:check` падает (exit 1), после отката — 0; четыре независимые сборки дали один дайджест.

### W8 — E2E и a11y — ✅ DONE

- **Playwright на `standalone.html`** (`web/playwright.config.ts`), backend не нужен: `/api/**` и `/ws/sessions/**`
  перехватываются моками. Мок-сервер (`web/e2e/mock-server.ts`) ведёт закрытый перечень эндпоинтов и пишет
  неизвестный вызов в `unmatched` — «виджет ходит мимо контракта» падает тестом, а не тихо проходит.
- **Матрица состояний — явный артефакт** (`web/e2e/state-matrix.ts`, 15 кадров): пустой диалог, восстановленная
  история, pending, ответ, ошибка сервера, HITL choice, HITL step-up, просроченная карточка, память save/forget/extract,
  вложение готово/отклонено, свёрнутая панель, светлая тема. Storybook не нужен (отклонение 11).
- **Проводной контракт** (`interaction.spec.ts`): тело и заголовки `intents.process` (токен, `x-trace-id`, `thread_id`),
  вложение через API при `memory://`-адресе хранилища, мутация памяти только через HITL-карточку, «Новый диалог»
  меняет `thread_id` без перезагрузки, regenerate переиспользует исходный запрос, feedback, 5xx-повторы (3 вызова),
  401 → ровно один refresh + один повтор, host-режим минтит токен хостом, step-up не пускает `respond` раньше времени.
- **Атрибуты хоста** (`host.spec.ts`): `lang` на элементе переключает интерфейс вживую — без перезагрузки страницы
  и без потери диалога (закрывает «переключение языка вживую» из W6).
- **a11y** (`a11y.spec.ts`): axe WCAG A/AA в тёмной и светлой темах (включая карточку HITL и панель памяти) —
  ноль нарушений; Tab с последнего контрола страницы-хоста заходит в виджет, порядок обхода совпадает с разметкой,
  у каждого шага видимый `outline: solid 2px`; Enter на варианте карточки открывает шаг подтверждения, а не выполняет
  действие; `prefers-reduced-motion` гасит появление, но сохраняет индикатор работы.
- **Визуальная сверка светлой темы** — кадры `web/.shots/` (пустой диалог, карточка инструмента, панель памяти,
  шаг подтверждения, свёрнутый лончер): палитра читаема, все поверхности и статусные цвета различимы, контраст
  подтверждён axe программно. Повтор — по запросу: `npm run test:shots` (4 кадра, в обычном прогоне пропускаются,
  чтобы не тащить картинки в CI). Ограничение: стенд `standalone.html` — тёмный фон страницы, а не светлый Bootstrap
  СЭД, поэтому «протечка» стилей хоста здесь не воспроизводится; её закрывает нейтрализация на `:host` (W4),
  окончательная проверка — на реальном СЭД-стенде (W9).
- **CI:** job `frontend` дополнен `npx playwright install --with-deps chromium` → `npm run test:e2e` → артефакт
  `playwright-report` + `test-results` (`if: always()`, иначе падение разбирать нечем).
- **DoD:** E2E зелёные (45 passed; прогон повторён без флаки) ✅; клавиатура и focus внутри Shadow DOM ✅;
  a11y-гейт на `standalone.html`, не на странице-хосте ✅.
- Побочно закрыты хвосты W4–W6: визуальная сверка светлой палитры (выше), «slow-motion в DevTools» заменён
  детерминированным тестом reduced-motion, переключение языка вживую — `host.spec.ts`, английские «утечки» при
  `lang=ru` — `findEnglishLeaks` в каждом кадре матрицы.
- Два дефекта виджета, найденные гейтом (оба исправлены): ошибка HITL определялась по ПОДСТРОКЕ статуса в тексте
  сервера — теперь `ApiError` несёт `status` числом (`src/api/client.ts`, решение принимается по коду, а не по
  формулировке «card expired»); параллельные эффекты старта (сокет + гидратация истории) выпускали по 5–6 dev-токенов —
  добавлена дедупликация «одного вылета» (`mintDevTokenOnce`), как в host-режиме (`pendingRefresh`).

### W9 — Интеграционный пакет для СЭД — ✅ закрыто на нашей стороне (стенд СЭД — их часть)

Документ для команды СЭД — `docs/embedded-assistant.md` §9 (адреса, события, каталог действий, токен, tenant,
монтаж, canary, требования к странице, чек-лист приёмки из 16 пунктов); §8 — только то, что требует их ответа.
Открытые пункты волны лежат не в нашем коде: обработчик `sed:action-requested` у СЭД (§9.2.1 даёт скелет),
производитель действия в виджете (§5 п.9 — продуктовое решение), `GE`, `thread_id`, живой стенд.

Что сделано в коде этой волной:

- **Адреса — один рычаг** (`web/src/runtime/endpoints.ts`): REST и WS выводятся из одной базы. До этого
  `VITE_API_BASE_URL` читал только `client.ts`, а сокет жёстко шёл на `window.location.host` — при
  относительной базе (штатная схема) это совпадало случайно, при абсолютной развело бы пути по разным origin.
  Проверка — `web/e2e/endpoints.spec.ts` (таблица «вход → ожидание» для 4 баз + наблюдаемое совпадение origin).
- **Tenant не передаётся клиентом:** поле `x-organization` в моке переименовано в `tenantHeader` и стало
  предметом проверки, а не заготовкой — `interaction.spec.ts` требует `null` на всех вызовах, включая host-режим.
  Прежняя формулировка плана («`x-organization` ↔ `scope.tenantId`») **отменена**: tenant берётся бэкендом из
  JWT-claim, `org_id` в теле роутер игнорирует (`routers/intents.py`), клиентский заголовок создал бы вторую
  точку правды (020).
- **Пути — часть контракта:** `ASSISTANT_API_PATH` / `ASSISTANT_WS_PATH` в `@palatium/contract` (что именно
  проксирует СЭД, больше не «деталь виджета»).
- **Каталог действий решён, а не вынесен в вопросы.** `AssistantAction` — размеченное объединение
  (`open_document` / `navigate` / `search`), вместо чернового `payload: Record<string, unknown>`: сырой dict
  на межкомандной границе — тот самый антипаттерн 050, который здесь и был. `navigate.view` — закрытый
  `SedViewKey` (`home`/`my_documents`/`my_tasks`), а не путь: маршруты принадлежат СЭД
  (`frontend/gtb/src/constants/content/route.js` — `HOME_PAGE_ROUTE`, `MY_DOCS_VIEW_ROUTE`, `MY_TASK_VIEW_ROUTE`),
  и принимать от ассистента произвольный path = отдать навигационный open-redirect в чужой UI. Разбор detail на
  стороне СЭД — только `isAssistantAction` (симметрично `isSedContext`). Эмиссия выключена не из-за контракта:
  у события нет **производителя** — `ContentDocument.actions` в виджете не рендерится, а его `ActionKind` это
  словарь платформы, не операции СЭД (отдельный вопрос §5 п.9). Каталог при этом самодостаточен: host реализует
  обработчик по скелету из §9.2.1 независимо от нас.
- **Граница доверия контекста — теперь проверяется, а не предполагается.** `checkTenantConsistency`
  сверяет `scope.tenantId`, `user.orgId` и claim токена (`org_id`, fallback `org` — как в
  `presentation/security/jwt.py`). Расхождение = host отдал контекст одной организации с токеном другой:
  сервер обслуживает tenant из токена, а UI показывает чужие данные — тихая кросс-tenant путаница. Поведение
  fail-closed (035): контекст отбрасывается, пользователь видит сообщение (`error.tenantMismatch`), окно
  автономного режима продолжает идти, `setContext()` бросает `TypeError`. Токен без claim (`e2e-token` стенда,
  dev-токен) — «неизвестно», подключение не блокируется. Проверка живёт в контракте, потому что она нужна
  обеим сторонам: host сам может её вызвать до отправки контекста.
- **`adoptedStyleSheets`-утверждение проверено кодом**: `csp-nonce` элементу не нужен (constructed stylesheet
  не проходит парсер документа), и это снято из документации как ошибочное требование к СЭД.
- **Дефект локали, найденный при разборе §5 п.3 (исправлен).** `resolveLocale` откатывался к
  `navigator.language`, когда `localization` не отображалась в BCP-47 (`GE`) — внутри русской страницы СЭД
  панель становилась англоязычной (язык браузера, а не host'а). Теперь при **наличии** контекста язык берётся
  из контекста, а неизвестное значение откатывается к RU — тому же, что рендерит сам СЭД для `GE`
  (`frontend/gtb/src/i18n.js`, `fallbackLng`); язык браузера остаётся источником только вне host'а.
  Регрессия — `e2e/host.spec.ts` (`locale: 'en-US'` + контекст `GE` → русский UI; проверено, что тест падает на
  прежней логике). Рычаг на случай будущих ресурсов `GE` — атрибут `lang` (покрыт тем же тестом).

Осталось (блокировано внешне, кода не касается):

- Стенд СЭД: `standalone` → реальный хост, живая проверка контекста и refresh (§9.8 пп. 1–4, 13, 15–16).
- Обработчик `sed:action-requested` в СЭД: каталог закрыт и типизирован (`AssistantAction`), скелет
  обработчика — §9.2.1. От СЭД нужны: маппинг `SedViewKey` → их `*_VIEW_ROUTE` и проверка права на раздел.
- Производитель действия в виджете — не продуктовое решение: он требует ссылок на документы СЭД в ответе,
  которых пока неоткуда взять (§5 п.9), то есть включается вместе с W13/EDMS MCP.
- Стенд СЭД закрывает непрерывность диалога: контракт готов с двух сторон (§9.2.2), от СЭД — подписка на
  `sed:thread-changed` и возврат id в контексте (референс — мок-хост `standalone.html`).

**DoD (скорректировано):** пакет и машиночитаемые проверки готовы; закрытие — на стенде СЭД (`standalone` →
реальный хост, контекст и refresh вживую, место в UI зафиксировано командой СЭД по §9.5). Пункт «UX-место»
остаётся открытым для СЭД, а не для нас: виджет поддерживает все три шаблона монтирования без правок кода.

---

### Track II — интеграция и бэкенд (W10–W13)

Предусловие каждой волны: **правка 070** (перечень инструментов) + обсуждение RBAC-маппинга. Без этого — не начинать.

#### W10 — Capability whitelist (`authorities` → tools)

> **Разделено на две части (решение 2026-09-29).** Генератор — разблокирован и делается сейчас.
> Привязка «инструмент → authority» — **блокирована** до ответа команды СЭД (§5 п.16): имена инструментов
> ещё не согласованы, а выдумать их нельзя (090).
>
> **Правка 070 выполнена:** правило описало несуществующий слой (`ToolDefinition`/`ToolPermission`/
> `ToolRegistry`), проверка живёт в `ToolExecutor.try_execute` (`application/tools/executor.py`), контракт
> инструмента — `PlatformToolPin` (`domain/mcp/tool_policy.py`). Правило приведено к коду — второй реестр
> НЕ создаётся (050).

- **W10a — генератор (DONE):** `scripts/gen_edms_authorities.py` читает enum `Permission`
  (`edms/security/model/Permission.java`, референс read-only, 090) и пишет
  `domain/mcp/edms_authorities.py`: 303 authority. Ось (`create`/`read`/`update`/`delete`/`other`)
  и ресурс выводятся из имени одним кодом (`classify_authority` в `domain/mcp/edms_permissions.py`) —
  префикс есть у 291 имени, 12 без префикса попадают в `other` осознанно. Ручной список
  запрещён (дрейф). Артефакт несёт `fingerprint` набора; гейт `tests/unit/test_edms_authorities.py`
  сверяет артефакт с референсом, когда референс есть (он в `.gitignore`), без него — внутреннюю
  согласованность и совпадение с собственным рендером (защита от ручной правки). JavaEdms в
  рантайм-пакет не попадает: копия генерируется, не импортируется (090).
- **W10b — привязка и гейт (блокировано §5 п.16):** какая `authority` требуется каждому инструменту
  (например, `search_documents` ← `READ_*`) — контракт СЭД, спрашиваем, не выдумываем. Проверка ляжет в
  единственную точку RBAC (`ToolExecutor` / `is_tool_invocation_allowed`), не middleware.
- Отказ — типизированный результат + audit `permission_denied` + `palatium_rbac_denied_total` (070.3),
  **не** `PermissionError` наружу (реализовано в `ToolExecutor.try_execute`).
- Серверные гейты: `fired → отказ запуска`; `archivist → read-only allow-list` (020: не UI-флаг).
- `authorities` в контексте — от host'а; токен валидируется, права берутся из токена/principal, а не из
  клиентского `SedContext` (клиентскому набору прав **не доверять** — Zero Trust).
- **DoD (W10a):** генератор + гейт зелёные; классификация осей не расходится с референсом; артефакт
  воспроизводим (`--check`).
- **DoD (W10b):** тесты «authority без права → отказ, не исключение»; «fired → ноль запусков»;
  «archivist → write-tool недостижим»; метрика растёт; audit-событие есть.

#### W11 — Scope-RAG и персонализация — ✅ DONE на нашей стороне (scope-фильтры заблокированы §5 п.16)

- Фильтры поиска по `departmentId` + `subordinatesDepartments` + `responsibleNomenclatureDepartmentIds` — **SQL/Cypher с параметрами** и обязательным tenant-scope (060: `WHERE user_id = :uid` + RLS), не `$or`-объекты.
- Параметризованные запросы; верхняя граница пагинации — из конфига (050).
- Персонализация: обращение по имени, локаль из `localization` (маппинг §5 п.3), формат дат/чисел по локали — **через слой i18n** (W6), не хардкод.
- Непрерывность диалога: тред переживает перезагрузку страницы СЭД (`SedContext.threadId` + `sed:thread-changed`, §5 п.5).
- **DoD:** тест «tenant A не видит tenant B»; scope-фильтр покрыт тестом на каждом источнике; даты/числа форматируются по локали; диалог продолжается в треде host'а.
- **Сделано (форматы локали, 2026-09-29):** формат чисел/дат — в единственном владельце локали
  (`web/src/i18n/index.ts`: `formatNumber` / `formatDateTime`), потребители переведены на него
  (`HitlCards.tsx` — срок карточки и `risk_score`, `ChatShell.tsx` — счётчик символов, `lib/attachments.ts` — размер файла).
  Исправлен дефект: `new Date(...).toLocaleTimeString()` на месте брал локаль **браузера** и внутри русской страницы
  СЭД давал `3:45:12 PM`; регрессия — `e2e/host.spec.ts` (RU и EN при браузере `en-US`). Формат следует
  **разрешённому языку интерфейса**, а не сырой строке локали: `de-DE`/`GE` не дают русский текст с немецкими разделителями.
- **Сделано (обращение по имени, 2026-09-29):** персонализация идёт от host'а: `preferredName` в контракте
  берёт `firstName`, иначе `fullName` **как есть** (`SedUser.fullName` — «host решает, что показывать»; разбор
  по позиции угадывал бы порядок «Фамилия Имя», 090), runtime отдаёт `userName`, пустое состояние рендерит
  `empty.greeting`. Автономно имени нет — приветствие не появляется (не «Здравствуйте, »). Тесты: `e2e/contract.spec.ts`
  (чистая функция: приоритет `firstName`, откат на `fullName`, `null`), `e2e/host.spec.ts` (контекст → UI, переключение языка).
- **Сделано (непрерывность диалога, 2026-09-30, §5 п.5):** тред живёт только в памяти сессии (storage запрещён, W3),
  поэтому перезагрузка страницы СЭД начинала бы диалог с нуля. Механизм двусторонний: host присылает
  `SedContext.threadId` → runtime принимает его (`adoptHostThread`, лимиты — `normalizeThreadId`: `1…128`, как у
  сервера), а когда тред создаёт сам виджет — объявляет его событием `sed:thread-changed`
  (`SedThreadChangedDetail`), чтобы host мог его сохранить. Три инварианта закреплены тестами:
  (1) host узнаёт ровно тот тред, которым виджет ходит в API; (2) после контекста с `threadId` виджет грузит
  историю **этого** тредa и продолжает в нём диалог (`intents.process` уходит с тем же id); (3) эха нет — id,
  присланный host'ом, обратно не объявляется (`AssistantRuntime.threadFromHost`). До конца рукопожатия виджет
  молчит: иначе host получил бы два разных тредa на один запуск. Событие добавлено в `custom-elements.json`
  (новый гейт в `tests/unit/test_frontend_widget_delivery.py`) и в референс мок-хоста `standalone.html`.
- **Осталось (блокировано):** scope-фильтры по подразделениям упираются в схему знаний — в `knowledge.documents`/`chunks`
  (`infrastructure/database/models/knowledge_chunk.py`) нет ни `department_id`, ни метаданных документа СЭД, а
  наполнение этих таблиц идёт из EDMS-инструментов, имена которых ещё не согласованы (§5 п.16). Плодить колонки
  «под будущий инструмент» — выдумывать контракт (090); порядок: сначала маппинг W10b/имена инструментов, затем
  колонки + параметризованные фильтры + тест «tenant A не видит tenant B».

#### W12 — Роли UUID → имена (только после решения §5)

- Источник: `GET /api/role/all` требует `READ_ROLE` (`RoleController.java:67`) — у обычного пользователя права может не быть.
- Варианты: (а) host резолвит имена и передаёт в контексте; (б) отдельный read-only эндпоинт СЭД; (в) остаться на UUID. Выбор — §5.
- Если кеш — только с лимитом + TTL + ключом по tenant; иначе не кешировать (050).
- **DoD:** имена отображаются или явно решено «только UUID»; кеш (если есть) ограничен и не течёт между tenant'ами.

#### W13 — Стриминг ответа и цитаты

- Протокол: расширить `/ws/sessions/{thread_id}` событиями (`chunk`/`tool_call`/`tool_result`/`citation`/`done`/`error`) **или** SSE — решение §5; не вводить третий путь.
- Отмена генерации (client abort) — обязательна; идемпотентность по `thread_id`.
- Цитаты источников в UI: контракт блока `ContentDocument` — расширение существующего типа, не новый «параллельный» документ.
- **DoD:** токены стримятся, tool-calls видимы, генерация прерывается; citation-блоки рендерятся и связаны с источниками; p95 первого токена измерен.

---

## 4. Гейты и артефакты

### 4.1. Гейты

| Гейт | Проверка |
|---|---|
| Ноль storage под токен/тред | grep `localStorage\|sessionStorage\|document.cookie` по `web/src` → пусто (кроме whitelist: ничего) |
| Bundle budget | размер `.iife.js` (gz) ≤ 150 KiB — энфорсится `build:widget` (падает) |
| Motion | нет `transition: all`, `scale(0)`, `ease-in` на UI, hover без `@media (hover: hover)` |
| XSS | тест: `BlockRenderer` не создаёт raw HTML (`innerHTML` недостижим); `safeHttpHref` отбивает `javascript:` |
| i18n | нет хардкод-строк — типизированные ключи (`Record<MessageKey, string>`); энфорсмент — за `084` (ESLint) |
| a11y | `npm run test:a11y` (CI: шаг `test:e2e`): axe WCAG A/AA в двух темах, Tab и видимый focus внутри Shadow DOM, контраст; визуальная сверка тем — `npm run test:shots` (вне CI) |
| E2E | `npm run test:e2e`: матрица 15 состояний + проводной контракт + адреса + атрибуты хоста + граница доверия контекста + локаль `GE` + форматы чисел/дат, обращение по имени и непрерывность диалога (49 тестов: 45 исполняются, 4 кадра по запросу; на `standalone.html`, backend не нужен) |
| Доставка | энфорсится CI-job `frontend`: `cem:check` (дрейф манифеста), `build:widget` (бюджет + валидность CEM), `verify:widget` (SRI + семвер). Артефакт — `palatium-assistant-widget` |

### 4.2. Пререквизиты к команде СЭД (не «придумать контракт» — согласовать)

1. Разрешить origin СЭД для `/api/*` (CORS) и `/ws/sessions/*`.
2. Отдавать `SedContext` из существующего `getMe()`/storage (поля — по `CurrentUser.java`, см. 2.1).
3. Реализовать ответ на `sed:assistant-context-requested` и `sed:auth-token-requested` — оба уже есть по смыслу в `fetchAuth.js` (`getMe`, `updateToken`).
4. Подтвердить достижимость presigned upload URL вложений из сети СЭД.

> Развёрнутая, проверяемая версия этих пререквизитов — `docs/embedded-assistant.md` §9 (там же чек-лист приёмки
> из 14 пунктов). Пункт 1 сведён к выбору топологии: **reverse proxy на origin СЭД** (CORS не нужен) или
> абсолютная база + CORS + WSS-allowlist — код поддерживает оба варианта одним рычагом
> (`VITE_API_BASE_URL`, `web/src/runtime/endpoints.ts`).

### 4.3. Куда какие артефакты (ответ на запрос «4 файла»)

Инструкция просит `AUDIT.md`, `ARCHITECTURE.md`, `ROADMAP.md`, `CHECKLIST.md`. В проекте уже есть владельцы этих тем — четыре новых файла в корне дадут дубли (050). Раскладка:

| Запрошено | Куда | Почему |
|---|---|---|
| `AUDIT.md` | **не создавать**: факты аудита живут в §1 этого плана и в правилах (000/030/040/060/070) | Аудит бэкенда уже разложен по правилам; второй файл = дубль (050) |
| `ARCHITECTURE.md` | `docs/embedded-assistant.md` — **сделано** (контракт элемента, handshake, темизация, доставка) | Durable-документ для команды СЭД; ADR по BFF — отдельно, когда BFF станет задачей |
| `ROADMAP.md` | **здесь**, `.cursor/plans/web-embed-assistant.md` | Второй ROADMAP = рассинхронизация (050) |
| `CHECKLIST.md` | **не создавать** | Гейты из 4.1 + правило `084-frontend-quality` энфорсят то же; чеклист без enforcement — не правило (hardening §0.2) |

Отклонение от §4.3: подкаталоги `docs/audit/` и `docs/architecture/` **не заводились** — `docs/` в проекте плоская
с индексом `docs/README.md`. Один durable-документ `docs/embedded-assistant.md` вместо двух: аудит-часть либо уже в
правилах, либо в §1 плана, а интеграционный контракт — то, что реально нужно команде СЭД (W9).

- Правило `084-frontend-quality` — владелец гейтов фронта (W4 плана `cursor-rules-hardening`).
- Новые запреты (если появятся) идут **в 050** или в своего владельца, а не в третий файл.
- Контракт `@palatium/contract` — владелец схемы событий между командами (§5 п.8).

---

## 5. Открытые вопросы (решения за пользователем)

**Зафиксировано в плане (дефолтом):**
- Single-file IIFE — базовый артефакт; lazy-load исключается, ESM — только если замер пробил бюджет.
- `SedContext` — минимальный, не зеркало `CurrentUser`.
- Motion-библиотека **не** добавляется (нет жестов, требующих spring).
- Storybook не добавляется; state-матрица — на `standalone.html`.
- Бэкенд **не** перепроектируется: Track II — четыре доработки (2.9), остальное уже есть.
- Capability whitelist — перечень authority генерируется из enum `Permission`; проверка — в единственной точке RBAC
  (`ToolExecutor` / `is_tool_invocation_allowed`, 070). Привязка tool→authority — по согласованию с СЭД (§5 п.16).
- Имена MCP-серверов и инструментов — по канону 070, не `sed-*`/`*_base`.
- Клиентскому `SedContext` **не** доверяем как источнику прав: права — из валидированного токена/principal (Zero Trust).
- **Версия-референс СЭД — `gtb`** (React 17, plain Redux, профиль в ключе `me`), подтверждено пользователем 2026-09-29; расхождения инструкции (`mi`, Redux Toolkit/RTK Query) **отброшены**.
- **Артефакты — рекомендованная раскладка** (§4.3), подтверждено пользователем: Audit/Architecture в `docs/`, ROADMAP только здесь, без `CHECKLIST.md`.
- **MCP-структура отложена** до ответа команды СЭД → W10 и W13 не начинать без решения (§5).

**Открыто (нужны решения пользователя):**

*Номера ниже стабильны: на них ссылаются `docs/embedded-assistant.md` и контракт, поэтому закрытые пункты
остаются на своих местах с пометкой «закрыто», а не удаляются.*

1. **Bundle-стратегия:** подтвердить IIFE-first (без lazy) или сразу ESM+CDN? (Влияет на W1/W7.)
2. **Auth-цель:** когда появляется BFF (`credentials:'include'`) — сейчас, в этом треке, или отдельной волной?
3. **`Localization.GE` — ✅ закрыто по поведению (2026-09-29).** Немецкий это или Грузия — вопрос к СЭД, но на
   поведение он больше не влияет: в `frontend/gtb/src/i18n.js` ресурсы есть только для `RU`/`EN`, а
   `fallbackLng` = RU, то есть СЭД сам рендерит русский для `GE`. Решение:
   `toBcp47('GE')` возвращает `null` («не BCP-47, который мы вправе назвать»), а runtime при **наличии**
   контекста берёт `ru-RU`, а не `navigator.language` (`src/runtime/store.ts`, `FALLBACK_LOCALE`) — иначе в
   русской странице появлялась бы англоязычная панель (это был реальный дефект, исправлен в W9;
   регрессия — `e2e/host.spec.ts`). Если развёртывание когда-нибудь добавит ресурсы для `GE`, СЭД задаёт язык
   атрибутом `lang` на элементе — рычаг уже есть и покрыт тестом.
4. **Порядок с правилом 084:** мержим W4 `cursor-rules-hardening` до W1 или вносим его гейты внутрь этого трека?
5. **`thread_id` в embed — ✅ закрыто (2026-09-30).** Механизм: `SedContext.threadId` (необязательное поле,
   `1…128` — те же лимиты, что у сервера, проверка в `normalizeThreadId`) плюс событие виджета
   `sed:thread-changed`, из которого host узнаёт id и возвращает его в следующем контексте. Атрибут элемента
   **отклонён осознанно**: `<palatium-assistant thread-id="…">` — статичная разметка страницы, общая для ВСЕХ
   пользователей, то есть один тред на всех (утечка диалога между людьми, 020). Динамический случай закрывает
   контекст, а объявлять атрибут, который никто не читает, — тот самый дефект, что уже исправлялся в 2.3.
   Детали и сценарий для СЭД — §9.2.2 `docs/embedded-assistant.md`; тесты — `e2e/host.spec.ts`
   (объявление своего треда, продолжение тредa host'а, отсутствие эха) и `e2e/contract.spec.ts` (лимиты).
6. **Место виджета в UI СЭД:** плавающая кнопка / боковая панель / отдельная страница — решение **команды СЭД**,
   не наше: виджет поддерживает все три шаблона без правок кода (в Shadow DOM нет ни `position`, ни `z-index`).
   В пакете W9 (§9.5 `docs/embedded-assistant.md`) для каждого шаблона приведён HTML и то, что стилизует СЭД;
   фиксация выбора нужна им, чтобы предсказуемо сверстать лончер.
7. **Маркировка untrusted-источника** (`web_fallback`) в выводе: точный формат пометки — согласовать с бэком (`domain/policies/untrusted_content.py`), не выдумывать.
8. **Кто владеет `web/packages/contract`** — эта команда или СЭД (CODEOWNERS)?
9. **Производитель `sed:action-requested` (W9) — ✅ снят: не продуктовый вопрос, а та же зависимость, что W10/W13.**
   Каталог закрыт и валидируем (`open_document`/`navigate`/`search`), но в виджете его никто не производит.
   `ContentDocument.actions` для этого не годится: это словарь HITL-карточек (промпт Formatter'а — «actions are
   specs only; the server turns them into clickable HITL cards»), `ActionKind` — закрытый enum платформы, и
   подмена оси смешала бы HITL с навигацией по СЭД (055, 090). Настоящий источник — ссылки на документы СЭД,
   которых в ответе нет: `meta.source_refs` во всём пайплайне пуст, инструментов с id документов СЭД не
   заведено (§5 п.16). Вывод: производитель включается вместе с retrieval/цитатами (W13) и EDMS MCP, отдельного
   решения он не требует.

**Открыто по расширенной инструкции (Фазы 1–4):**

*Снято решением пользователя 2026-09-29: версия-референс СЭД — `gtb` (React 17, plain Redux, профиль в `me`); артефакты — раскладка §4.3.*

10. **Cross-encoder реранкер:** вводить (новая модель + латентность) или оставить существующий embedding-rerank (`embedding_rerank.py`)?
11. **Стриминг:** расширять `/ws/sessions/{thread_id}` событиями или вводить SSE? (W13.)
12. **Роли UUID → имена:** host резолвит / отдельный read-only эндпоинт СЭД (`READ_ROLE` у пользователя может отсутствовать) / остаёмся на UUID? (W12.)
13. **Аудит СЭД:** писать ли действия ассистента в аудит СЭД, и в каком контракте? (Сегодня аудит — hash-chained в Palatium.)
14. **OWASP LLM — ✅ закрыто (2026-09-30): год и в правилах, и в коде не хардкодится.** Ссылки на LLM-риск в коде —
    без года (`core/security/prompt_injection.py`, `domain/policies/untrusted_content.py`, `domain/policies/types.py`:
    «OWASP LLM01»), а подтверждённая база веб-топа (OWASP Top 10:2025, A01–A10) — в `035-error-handling.mdc`
    и `plans/cursor-rules-hardening.md` §1. Спорная формулировка «LLM01:2026» жила только в черновике инструкции
    и в план не переносилась.
15. **Neo4j Browser как эталон:** подтвердить источник ключей (`plgAssistant.*`, `agentChat.visible`, `kgBuilder`) или снять из входных данных как непроверенное.
16. **MCP-структура (отложено):** расширять `edms` + правка 070 или заводить `sed-*` — ждём команду СЭД. Блокирует W10 (имена инструментов) и W13.
17. **Feedback персистится — ✅ закрыто (2026-10-05).** Виджет шлёт like/dislike/clear на
    `POST /api/feedback`; бэкенд пишет в `palatium_ai.message_feedback` (FORCE RLS, миграция
    `f6a7b8c9d0e1`). Агрегаты для evals / admin-отчётов — отдельная задача поверх таблицы.

---

## Приложение A — исправленная инструкция для Cursor (готовый промпт)

> Ты — ведущий frontend-архитектор embeddable-виджета. Преврати `web/` проекта Palatium-AI в Web Component `<palatium-assistant>` с Shadow DOM, пригодный для встраивания в СЭД «Канцлер».
>
> **Отправная точка (проверено, не выдумывай иное):** `react ^19.1.1`, `vite ^7.1.5`, `typescript ~5.9.2`, `lucide-react ^0.544`, `lottie-react ^3.1`, `react-hot-toast ^2.6`. Стили — plain CSS (`web/src/styles.css`), Tailwind нет. Shadow DOM, `customElements`, `prefers-reduced-motion` в проекте **отсутствуют** — начинаешь с нуля. Тестовой инфраструктуры в `web/` нет.
>
> **Контекст интеграции:** реального СЭД-подключения нет, но контракт проектируется как боевой. Модель пользователя СЭД — по `mcp_servers/edms/JavaEdms/edms/controller/response/CurrentUser.java` (read-only reference, 090): `id:UUID`, `orgId`, `firstName/lastName/middleName`, `fullPostName`, `departmentId:UUID`, `departmentName`, `postId:Long`, `post:PostDto{id,postName,postCode}`, `country:CountryDto`, `localization: Localization{RU|EN|GE}`, `active`, `fired`, `authorities`, `roles:Set<UUID>`, `responsibleNomenclatureDepartmentIds`, `subordinatesDepartments`, `archivist`, `widgets`, `scanWia`, `docEllipsis`, `showEventDesign`. Хост хранит JWT+refresh в `localStorage`, `me` — в `sessionStorage` (`frontend/gtb/src/scripts/fetchAuth.js`), WS — SockJS/STOMP. **Не копируй DTO целиком:** контракт виджета — минимальный (только читаемые поля). Где данных не хватает — спроси, не изобретай.
>
> **Что сделать:**
> 1. `web/packages/contract/` — `SedUser` (минимальный), `SedPermissions`, `SedDocumentRef`, `SedContext`, `SED_EVENTS`. Подключить npm workspaces в `web/package.json` + TS project references. Собирать ESM+CJS+`.d.ts`.
> 2. `web/src/widget.tsx` — `<palatium-assistant>`, Shadow DOM `mode:'open'`. Использовать `adoptedStyleSheets` + constructed `CSSStyleSheet` (не `<style>`), CSS из `./styles.css?inline`. Публичный API: `open()`, `close()`, `setContext(ctx)`. Событие `palatium:ready`. **Root React создаётся один раз и не уничтожается в `disconnectedCallback`** (элемент могут перемещать по DOM). Реализовать `attributeChangedCallback`, если объявлены `observedAttributes`.
> 3. `web/vite.config.wc.ts` — library mode, IIFE, single-file, `inlineDynamicImports: true`, `target: 'es2022'`, без `manualChunks`. **Помни: IIFE + lazy-load несовместимы** — никаких динамических `import()` в этом артефакте; шрифты/ассеты либо инлайнятся, либо system stack.
> 4. `web/src/lib/hostContext.ts` — двусторонний bridge: слушает `sed:context-changed`, `sed:auth-token-refreshed`; шлёт `sed:assistant-context-requested` (при connect), `sed:auth-token-requested`, `sed:action-requested`. Дополнительно читает `window.__palatiumSedContext` (host мог выставить контекст до загрузки скрипта). Fallback → standalone **только** если после отправки запроса прошло 500 ms без ответа. Слушать и `window`, и сам элемент.
> 5. `web/src/api/client.ts` — токен только в module-level переменной; `setToken`/`setMode('host'|'standalone')`; refresh через событие; 401 — один retry. Убрать `sessionStorage`/`localStorage`. `mintDevToken` (`/auth/dev-token`) вызывать **только** в standalone. `trace.ts` — trace-id в памяти.
> 6. `web/src/components/ChatShell.tsx` — убрать `resolveThreadId/UserId/OrgId` (storage), брать из `SedContext`; `startNewThread()` **не** вызывает `window.location.reload()` (виджет не перезагружает страницу СЭД).
> 7. `web/src/styles.css` — добавить motion-токены `--ease-out: cubic-bezier(0.23,1,0.32,1)`, `--ease-in-out: cubic-bezier(0.77,0,0.175,1)`, `--ease-drawer: cubic-bezier(0.32,0.72,0,1)`, `--duration-press…drawer`; `:host`-токены темизации + light/dark; `::part()` для публичных зон. **Никаких cubic-bezier под видом spring** — spring в CSS только через `linear(...)`, и он проекту не нужен.
> 8. Motion-полировка: `:active { transform: scale(0.97) }` 120 ms на pressable (в т.ч. `.action-btn`, сейчас `0.9`); hover-эффекты только под `@media (hover: hover) and (pointer: fine)`; `transform-origin` от триггера для popover (modal — по центру); stagger 30–80 ms для `.hitl-stack > .hitl-card`. Запрещено: `transition: all`, `scale(0)`, `ease-in` на UI, анимация `width/height/margin/padding/top/left`.
> 9. `@media (prefers-reduced-motion: reduce)` — **скоупить**: убрать `transform`-движение, сохранить opacity/color и статус-индикаторы (`spin`, `dotPulse`). Не использовать глобальный `animation-duration: 0.01ms !important`.
> 10. `custom-elements.json` (`@custom-elements-manifest/analyzer`); `web/standalone.html` с mock-контекстом и матрицей состояний (пусто, pending, HITL, память, вложение, ошибка).
> 11. Тесты: unit на клиент/handshake (Vitest) + Playwright на критические сценарии. Никакого raw HTML в рендере блоков — покрыть тестом, что `BlockRenderer` не создаёт HTML из вывода модели.
>
> **Не делать:** не менять бэкенд-контракты; не переписывать `BlockRenderer`, `HitlCards`, `MemoryActions`; не добавлять Framer Motion/GSAP/Redux/Storybook; не делать SSR; не тащить Google Fonts; не коммитить `dist`/`node_modules`.
>
> **DoD:** `<palatium-assistant>` работает на `standalone.html` без host'а; при `sed:context-changed` (в т.ч. до `palatium:ready`) получает токен и пользователя; 401 проходит через `sed:auth-token-requested`; grep по `web/src` — ноль storage под токен/тред; bundle в бюджете; нет `transition: all`/`scale(0)`/`ease-in`; reduced-motion работает и не «замораживает» лоадеры; `custom-elements.json` валиден; E2E зелёные.

---

## Приложение B — исправленная расширенная инструкция (Фазы 1–4, для Cursor)

Промпт ниже — переписанная версия расширенной инструкции. Все проверенные факты вставлены как данность; неверные утверждения убраны; конфликты с правилами заменены на корректные механизмы.

> Ты — ведущий архитектор AI-ассистента корпоративного уровня. Проведи аудит Palatium-AI (Python + React) и СЭД «Канцлер» и составь план встраиваемого ассистента. Работай в четыре фазы; артефакты кладёшь по §4.3 этого плана (**не** создавай второй ROADMAP и CHECKLIST).
>
> **Проверенные факты — не перепроверяй и не выдумывай иное:**
>
> *Palatium-AI (бэкенд):* FastAPI; orchestrator — **LangGraph** (уже выбран, менять нельзя); MCP — канон серверов `{platform, edms, analytics}`, platform = Host-local discovery + handler; **закрытый** перечень инструментов (070): `search_knowledge`, `search_memory`, `save_memory`, `forget_memory`, `extract_transcript_memories`, `ingest_document`, `graph_query`, `web_fallback`. RBAC — **`ToolExecutor.try_execute` над `PlatformToolPin` + `allowed_tools`** (единственная точка), отказ — типизированный результат + audit `permission_denied` + метрика, **никогда** не `PermissionError` наружу (070.3). Поиск — Postgres FTS `ts_rank_cd` + pgvector-косинус + опциональный embedding-rerank; **не** называть это «BM25» (060). Изоляция — RLS `FORCE ROW LEVEL SECURITY` + обязательный tenant-scope (`$tenant_param`) + `WHERE user_id = :uid`. Стриминг: HTTP `POST /intents/process`; WS `/ws/sessions/{thread_id}` — только events/keepalive. Rate limit — `RateLimitMiddleware` (есть). Audit — hash-chained + события (040). Observability — OTel + реестр метрик (040).
>
> *Palatium-AI (фронтенд `web/`):* `react ^19.1.1`, `vite ^7.1.5`, `typescript ~5.9.2`, `lucide-react ^0.544`, `lottie-react ^3.1`, `react-hot-toast ^2.6`; plain CSS (`web/src/styles.css`), Tailwind нет. **Shadow DOM / `customElements` / `prefers-reduced-motion` отсутствуют** — начинать с нуля. Тестов в `web/` нет. Токен сейчас в `sessionStorage`, тред/user/org — в `localStorage`; `startNewThread()` перезагружает страницу — всё это исправить.
>
> *СЭД «Канцлер» (референс в репо, read-only, 090):* `mcp_servers/edms/JavaEdms`. Mодель пользователя — `edms/controller/response/CurrentUser.java`: `id:UUID`, `orgId`, `firstName/lastName/middleName`, `fullPostName`, `departmentId:UUID`, `departmentName`, `postId:Long`, `post:PostDto{id,postName,postCode}`, `country:CountryDto{id,code,shortName,fullName,alphaCodeTwo,alphaCodeThree,active}`, `localization: enum{RU,EN,GE}`, `active`, `fired`, `authorities`, `roles:Set<UUID>`, `responsibleNomenclatureDepartmentIds`, `subordinatesDepartments`, `archivist`, `griefIds`, `meIo`, `settings`, `views`, `widgets`, `scanWia`, `docEllipsis`. `authorities` — константы enum `Permission` (≈302), например `CREATE_SYNCHRONIZATION_TASK_SAP`, `CREATE_ACCESS_GRIEF`, `CREATE_COUNTRY`, `DELETE_WORK_CALENDAR`. Frontend `gtb`: React 17, **plain Redux** (не RTK), `react-router-dom 5`, axios с interceptor-retry, JWT+refresh в `localStorage`, профиль в `sessionStorage` под ключом `me`; WS — SockJS/STOMP. `GET /api/role/all` требует `READ_ROLE`.
>
> *Если факты не совпадают с тем, что ты видишь в другой версии СЭД (`mi`, Redux Toolkit) — спроси, не выбирай сам.*
>
> **Делать:**
>
> 1. **Track I (виджет, W0–W9 плана).** `@palatium/contract` (минимальный `SedContext`, не зеркало DTO) → `<palatium-assistant>` (Shadow DOM open, `adoptedStyleSheets`, root не уничтожать в `disconnectedCallback`, `attributeChangedCallback`) → `vite.config.wc.ts` (IIFE single-file, **без** lazy-load) → двусторонний handshake (`sed:assistant-context-requested` + чтение `window.__palatiumSedContext`; standalone только если 500 ms без ответа **после** запроса) → токен только в памяти (`setToken`/`setMode`; `mintDevToken` только в standalone) → motion-токены, scoped `prefers-reduced-motion`, hover-гейт → темизация `:host`/`::part()` без Google Fonts → i18n (RU/EN + маппинг `GE`) → CEM + standalone → Playwright + a11y.
> 2. **Track II (бэкенд, W10–W13) — правка 070 выполнена 2026-09-29 (правило приведено к коду: `PlatformToolPin` + `ToolExecutor`), W10a (генератор authority) сделан.** Остаётся capability whitelist: **привязка authority→tools — по согласованию с СЭД** (§5 п.16), проверять в единственной точке RBAC (`ToolExecutor`), отказ — типизированный + audit + метрика; `fired`/`archivist` — **серверные** гейты; права брать из валидированного токена, а не из клиентского `SedContext`. Scope-RAG — параметризованные SQL/Cypher по `departmentId` + `subordinatesDepartments` + `responsibleNomenclatureDepartmentIds` с tenant-scope и RLS. Стриминг + citations — по решению (WS-расширение или SSE). Роли UUID→имена — после решения об источнике.
> 3. **Персонализация:** имя из `firstName`, локаль из `localization` (маппинг enum → BCP-47 — уточнить `GE`), формат дат/чисел по локали, через слой i18n.
> 4. **Безопасность:** токен только в памяти; никакого `localStorage`/`sessionStorage`/`cookie` под токен/тред (grep-гейт); клиентскому набору прав не доверять; никакого raw HTML из вывода модели (покрыть тестом); BFF — **целевая** архитектура (ADR отдельно); маркировка untrusted-источников — по контракту бэка, не выдумывать.
>
> **Не делать:** не менять оркестратор (LangGraph), не переименовывать инструменты и MCP-серверы мимо 070, не вводить namespace-per-tenant поверх RLS, не объявлять «BM25/RRF», не заменять существующий rerank на cross-encoder без решения, не создавать 4 сервера `sed-*`, не делать SSR, не добавлять Framer Motion/GSAP/Redux/Storybook, не тащить Google Fonts, не создавать второй ROADMAP/CHECKLIST, не выдумывать контракты СЭД (090).
>
> **Выход:** волны — в этом плане; `docs/audit/embedded-assistant.md` (только новые факты); `docs/architecture/embedded-assistant.md` с Mermaid + контрактом событий; ADR по BFF. Каждый пункт чеклиста из инструкции либо **энфорсится гейтом** (§4.1), либо в план не попадает.
