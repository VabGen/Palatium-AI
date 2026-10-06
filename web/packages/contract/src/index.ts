/**
 * @palatium/contract — контракт встраивания ассистента в СЭД «Канцлер».
 *
 * Это ЕДИНСТВЕННЫЙ источник истины для событий и форм данных между
 * командой СЭД и виджетом <palatium-assistant>. Изменение любого поля
 * или имени события = изменение контракта обеих команд (правило 005),
 * а не локальная правка в PR одной стороны.
 *
 * Контракт намеренно МИНИМАЛЬНЫЙ: только то, что виджет реально читает.
 * Копия внутренней модели СЭД (`CurrentUser.java`, read-only, правило 090)
 * здесь запрещена — она дрейфует и связывает виджет с чужими DTO (050, YAGNI).
 */

/** Локализация СЭД. Enum JavaEdms `Localization`. НЕ BCP-47 — маппинг см. `toBcp47`. */
export type SedLocalization = 'RU' | 'EN' | 'GE';

/** Отображаемое имя пользователя. Вычисляет host — виджет не склеивает ФИО сам. */
export interface SedUser {
  /** UUID пользователя СЭД. */
  readonly id: string;
  /** Tenant ID (`orgId` в СЭД). Обязателен: используется как scope изоляции. */
  readonly orgId: string;
  /** Готовое к показу имя (host решает, что именно показывать). */
  readonly fullName?: string;
  /** Отдельные части имени — для персонализированного обращения. */
  readonly firstName?: string;
  readonly lastName?: string;
  readonly middleName?: string;
  readonly departmentId?: string;
  readonly departmentName?: string;
  readonly localization?: SedLocalization;
  /** `active` в СЭД: false → аккаунт выключен. */
  readonly active?: boolean;
  /** `fired` в СЭД. Серверный гейт: виджет показывает только UX-состояние. */
  readonly fired?: boolean;
}

/**
 * Права пользователя.
 *
 * ВАЖНО (Zero Trust): эти данные приходят от host и используются ТОЛЬКО для UX
 * (что показывать/скрывать). Авторизация на бэкенде опирается на валидированный
 * токен, а не на этот объект (020, 070).
 */
export interface SedPermissions {
  /** `authorities` — GrantedAuthority из `Permission.java` (capability whitelist). */
  readonly authorities: readonly string[];
  /** `roles` — Set<UUID> в СЭД. */
  readonly roles: readonly string[];
  /** Расширенный скоуп видимости документов. */
  readonly responsibleNomenclatureDepartmentIds?: readonly string[];
  readonly subordinatesDepartments?: readonly string[];
  /** `archivist` в СЭД. Серверный гейт: read-only профиль инструментов. */
  readonly archivist?: boolean;
}

/** Текущий открытый документ СЭД — контекст запроса, не источник прав. */
export interface SedDocumentRef {
  readonly id: string;
  readonly type?: string;
  readonly departmentId?: string;
  /** Заголовок для отображения в контекстной плашке виджета. */
  readonly title?: string;
}

/** Полный контекст, который host передаёт виджету. */
export interface SedContext {
  /**
   * Короткоживущий access token.
   *
   * Требование безопасности: живёт ТОЛЬКО в памяти виджета. Никогда не пишется
   * в localStorage / sessionStorage / cookie и не попадает в логи.
   */
  readonly token: string;
  readonly user: SedUser;
  readonly permissions?: SedPermissions;
  /** Открытый документ — контекст текущего запроса. */
  readonly document?: SedDocumentRef;
  /** Scope изоляции. `tenantId` = `user.orgId`. */
  readonly scope: SedScope;
  /** Пользовательские настройки СЭД (`widgets`, `docEllipsis`, `showEventDesign`). */
  readonly settings?: Readonly<Record<string, unknown>>;
  /**
   * Тред диалога, который host уже ведёт (пережил перезагрузку страницы СЭД).
   *
   * Тред живёт в памяти сессии виджета, а storage запрещён (W3), поэтому после
   * перезагрузки диалог начинался бы с нуля. Сохранить id может только host — он
   * же возвращает его здесь, и виджет продолжает тот же диалог. Как host узнаёт
   * id: виджет объявляет его событием `sed:thread-changed` (`SedThreadChangedDetail`).
   *
   * Значение — **не** источник прав (Zero Trust): и `GET /api/sessions/{id}/turns`,
   * и WS `/ws/sessions/{id}` проверяют владельца на сервере, поэтому чужой id даёт
   * пустой диалог и отказ подписки, а не чужие данные (020). Формат и длину
   * проверяйте через `normalizeThreadId` — там же, где остальные правила данных.
   */
  readonly threadId?: string;
}

export interface SedScope {
  /** = `user.orgId`. Используется бэкендом для tenant-изоляции. */
  readonly tenantId: string;
  /** `[user.departmentId]` ∪ subordinates ∪ responsible — без дублей. */
  readonly departmentIds: readonly string[];
}

/**
 * Разделы СЭД, в которые виджет вправе попросить переход.
 *
 * Закрытый перечень ключей, а НЕ путь: маршруты принадлежат СЭД
 * (`frontend/gtb/src/constants/content/route.js`) и меняются без нас. Host сам
 * отображает ключ в свой `*_VIEW_ROUTE` и проверяет право на раздел. Принимать
 * от ассистента произвольный путь = открыть навигационный open-redirect в чужом UI.
 */
export type SedViewKey = 'home' | 'my_documents' | 'my_tasks';

/** Общие поля любого действия: корреляция с трассировкой и обязанность хоста спросить. */
interface AssistantActionBase {
  /** Корреляция с трассировкой Palatium (040); host логирует её рядом со своим действием. */
  readonly correlationId?: string;
  /**
   * true → host обязан показать подтверждение ПЕРЕД выполнением.
   *
   * Виджет выставляет флаг только для необратимых просьб (020); сегодняшний
   * каталог обратим (навигация/открытие карточки), поэтому поле здесь —
   * контрактная возможность, а не текущее поведение.
   */
  readonly requiresConfirmation?: boolean;
}

/** Открыть карточку документа в UI СЭД. Обратимо: HITL не требуется. */
export interface OpenDocumentAction extends AssistantActionBase {
  readonly action: 'open_document';
  /**
   * Идентификатор документа, который СЭД подставляет в свой маршрут карточки
   * (`DOCUMENT_FORM_ROUTE/:id`) — суррогатный id, а не бизнес-номер: номеров у
   * типа документа может быть несколько, и по ним роут не строится.
   */
  readonly documentId: string;
}

/** Перейти в раздел СЭД из закрытого перечня `SedViewKey`. */
export interface NavigateAction extends AssistantActionBase {
  readonly action: 'navigate';
  readonly view: SedViewKey;
}

/** Открыть поиск СЭД с заполненным запросом. */
export interface SearchAction extends AssistantActionBase {
  readonly action: 'search';
  readonly query: string;
}

/**
 * Действие, которое виджет просит выполнить СЭД (`sed:action-requested`).
 *
 * Размеченное объединение, а не `payload: Record<string, unknown>`: сырой dict в
 * контракте — потеря типобезопасности на границе (050) и дрейф между командами.
 * Каталог ЗАКРЫТ: новый вариант = правка этого union обеими командами (005),
 * а не «произвольное действие строкой».
 *
 * Эмиссия события сегодня ВЫКЛЮЧЕНА, и причина не в контракте: в ответе ассистента
 * нет ссылок на документы СЭД. `ContentDocument.actions` для этого не годится —
 * это словарь HITL-карточек (промпт Formatter'а: «actions are specs only; the
 * server turns them into clickable HITL cards»), а его `ActionKind` — закрытый
 * enum платформы, не операции СЭД; подстановка смешала бы две оси (055, 090).
 * `open_document` требует `documentId`, а `meta.source_refs` во всём пайплайне
 * пуст и инструментов с id документов СЭД ещё нет (см. план §5 п.16) — то есть
 * производитель включается вместе с retrieval/цитатами (W13), а не отдельным
 * решением. Типы ниже согласованы заранее, чтобы host мог реализовать обработчик
 * (скелет — `docs/embedded-assistant.md` §9.2.1) независимо от нас.
 *
 * Решения принимает host: он может отклонить любую просьбу (нет права, раздел
 * недоступен). Виджет не считает переход выполненным, пока не увидит смену
 * контекста (`sed:context-changed`) или `document`.
 */
export type AssistantAction = OpenDocumentAction | NavigateAction | SearchAction;

/** Payload события `sed:action-requested`. */
export type ActionRequestedDetail = AssistantAction;

/** Payload события `sed:auth-token-refreshed`. */
export interface SedTokenRefreshedDetail {
  readonly token: string;
}

/** Payload события `sed:thread-changed`. */
export interface SedThreadChangedDetail {
  /** Текущий тред диалога; host сохраняет его и возвращает в `SedContext.threadId`. */
  readonly threadId: string;
}

/**
 * Имена событий. Обе стороны импортируют ОТСЮДА — строковые литералы в коде
 * приложения запрещены (иначе опечатка в одном месте ломает интеграцию молча).
 */
export const SED_EVENTS = {
  /** СЭД → виджет: контекст впервые или при смене пользователя/документа. */
  CONTEXT_CHANGED: 'sed:context-changed',
  /** Виджет → СЭД: «пришли контекст» (handshake, снимает гонку до `customElements.define`). */
  CONTEXT_REQUESTED: 'sed:assistant-context-requested',
  /** СЭД → виджет: обновлённый access token. */
  TOKEN_REFRESHED: 'sed:auth-token-refreshed',
  /** Виджет → СЭД: «токен протух, обнови» (после 401). */
  TOKEN_REQUESTED: 'sed:auth-token-requested',
  /**
   * Виджет → СЭД: «диалог идёт в этом треде».
   *
   * Нужен ровно для одного: host сохраняет id у себя и в следующий раз присылает
   * его в `SedContext.threadId`, иначе перезагрузка страницы стирает диалог.
   * В ответ host контекст НЕ пересылает — событие одностороннее, иначе интеграция
   * замкнула бы цикл «контекст → тред → контекст».
   */
  THREAD_CHANGED: 'sed:thread-changed',
  /** Виджет → СЭД: запрос выполнения действия в системе (каталог — `AssistantAction`). */
  ACTION_REQUESTED: 'sed:action-requested',
  /** Виджет → СЭД: кастомный элемент апгрейдился и готов принимать контекст. */
  ASSISTANT_READY: 'palatium:ready',
} as const;

export type SedEventName = (typeof SED_EVENTS)[keyof typeof SED_EVENTS];

/**
 * Контекст, выставленный host'ом ДО загрузки скрипта виджета.
 *
 * Снимает гонку: СЭД может положить контекст в window раньше, чем
 * `customElements.define` апгрейдит элемент (см. план §2.2).
 */
declare global {
  interface Window {
    __palatiumSedContext?: unknown;
  }
}

/** Тег кастомного элемента. */
export const ASSISTANT_TAG = 'palatium-assistant' as const;

/**
 * Пути, которые СЭД обязана маршрутизировать на Palatium-AI.
 *
 * Часть контракта, а не деталь виджета: от их доступности зависит вся работа
 * виджета (REST) и индикатор треда (WS). Штатная схема — reverse proxy на origin
 * СЭД, тогда CORS не нужен вовсе; см. `docs/embedded-assistant.md` §9.1.
 */
export const ASSISTANT_API_PATH = '/api' as const;
export const ASSISTANT_WS_PATH = '/ws/sessions' as const;

/**
 * Локализация СЭД → BCP-47.
 *
 * `GE` объявлена в enum JavaEdms, но ресурсов для неё в СЭД нет: их `i18n.js`
 * знает только `RU`/`EN` и откатывается на RU. Поэтому здесь `GE` → `null`
 * («не BCP-47, который мы вправе назвать»), а политика отката живёт в runtime:
 * при наличии контекста виджет берёт язык host'а (`ru-RU`), а не язык браузера —
 * см. `src/runtime/store.ts`, `FALLBACK_LOCALE`. Так «немецкий или Грузия»
 * перестаёт влиять на поведение; если развёртывание когда-нибудь добавит ресурсы
 * для `GE`, СЭД задаёт язык атрибутом `lang` на элементе.
 */
export function toBcp47(localization: SedLocalization | undefined): string | null {
  switch (localization) {
    case 'RU':
      return 'ru-RU';
    case 'EN':
      return 'en-US';
    case 'GE':
      return null;
    default:
      return null;
  }
}

/** Объединяет источники скоупа в один список без дублей и пустых значений. */
export function buildDepartmentScope(
  departmentId: string | undefined,
  permissions: SedPermissions | undefined
): string[] {
  const scope = new Set<string>();
  if (departmentId) scope.add(departmentId);
  for (const id of permissions?.subordinatesDepartments ?? []) {
    if (id) scope.add(id);
  }
  for (const id of permissions?.responsibleNomenclatureDepartmentIds ?? []) {
    if (id) scope.add(id);
  }
  return [...scope];
}

/**
 * Имя для персонализированного обращения («Здравствуйте, Иван»).
 *
 * Порядок: `firstName` — host явно назвал форму обращения; иначе `fullName`
 * КАК ЕСТЬ. Разбирать `fullName` по позиции нельзя: контракт говорит «host
 * решает, что именно показывать», а порядок («Фамилия Имя» или «Имя Фамилия»)
 * в СЭД не зафиксирован — угадывание дало бы обращение по фамилии (090: не
 * выдумывать семантику СЭД). `null` — обращаться не по чему, шаблон без имени.
 */
export function preferredName(user: SedUser | undefined): string | null {
  const first = user?.firstName?.trim();
  if (first) return first;
  const full = user?.fullName?.trim();
  return full ? full : null;
}

/**
 * Предел длины `thread_id` — тот же, что у сервера.
 *
 * Источник истины — `UpsertSessionRequest.thread_id` в
 * `presentation/api/routers/sessions.py` (`Field(min_length=1, max_length=128)`).
 * Значение лежит здесь, потому что проверять его надо на ГРАНИЦЕ (контекст
 * host'а — недоверенный ввод), а не после отклонённого запроса: иначе лимит
 * дублировался бы в виджете вторым числом (050).
 */
export const THREAD_ID_MAX_LENGTH = 128;

/**
 * Приводит тред из недоверенного источника к значению, которое примет сервер.
 *
 * `null` — «не тред»: не строка, пустая/пробельная или длиннее лимита. Возврат
 * `null` вместо исключения осознан: контекст host'а может прийти с мусором в
 * одном поле, и терять из-за него весь контекст (токен, локаль, права) хуже,
 * чем продолжить с новым тредом.
 */
export function normalizeThreadId(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > THREAD_ID_MAX_LENGTH) return null;
  return trimmed;
}

/**
 * Валидирует контекст на границе доверия.
 *
 * Виджет принимает контекст из `CustomEvent`, который может быть отправлен
 * кем угодно на странице host — мусорный payload обязан быть отброшен здесь,
 * а не уронить рендер (035: fail-closed на границе).
 */
export function isSedContext(value: unknown): value is SedContext {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Partial<SedContext>;
  if (typeof candidate.token !== 'string' || candidate.token.trim().length === 0) return false;

  const user = candidate.user as Partial<SedUser> | undefined;
  if (typeof user !== 'object' || user === null) return false;
  if (typeof user.id !== 'string' || user.id.trim().length === 0) return false;
  if (typeof user.orgId !== 'string' || user.orgId.trim().length === 0) return false;

  const scope = candidate.scope as Partial<SedScope> | undefined;
  if (typeof scope !== 'object' || scope === null) return false;
  if (typeof scope.tenantId !== 'string' || scope.tenantId.trim().length === 0) return false;
  if (!Array.isArray(scope.departmentIds)) return false;

  return true;
}

/**
 * Claims JWT БЕЗ проверки подписи.
 *
 * Подпись проверяет только бэкенд Palatium (`presentation/security/jwt.py`);
 * виджет разбирает payload исключительно для сверки согласованности контекста
 * (см. `checkTenantConsistency`) и никогда не выводит из него прав. `null` —
 * «не JWT или payload нечитаем»: это неизвестность, а не ошибка.
 */
export function jwtClaims(token: string): Readonly<Record<string, unknown>> | null {
  const [, payload] = token.split('.');
  if (payload === undefined || payload.length === 0) return null;
  try {
    const binary = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
    const parsed: unknown = JSON.parse(new TextDecoder().decode(bytes));
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) return null;
    return parsed as Record<string, unknown>;
  } catch {
    // Битый base64 или не-JSON payload: для сверки это «неизвестно», не падение.
    return null;
  }
}

/**
 * Tenant из claims токена — те же имена, что читает бэкенд
 * (`presentation/security/jwt.py`: `org_id` либо `org`).
 *
 * `null` — claim отсутствует: токен выпущен без tenant'а (например, dev-токен
 * или IdP без организаций), сверять нечего.
 */
export function tokenTenantId(token: string): string | null {
  const claims = jwtClaims(token);
  if (claims === null) return null;
  for (const claim of ['org_id', 'org'] as const) {
    const value = claims[claim];
    if (typeof value === 'string' && value.trim().length > 0) return value.trim();
  }
  return null;
}

/**
 * Вердикт согласованности tenant'а в контексте host'а.
 *
 * - `ok` — `user.orgId`, `scope.tenantId` и claim токена совпадают;
 * - `unknown` — токен не несёт tenant-claim (сверять нечего, принимаем);
 * - `mismatch` — данные противоречат друг другу.
 *
 * Зачем проверять в виджете, если tenant берётся из валидированного токена:
 * при расхождении сервер обслуживает ОДИН tenant (тот, что в токене), а хост
 * думает, что работает с другим — это тихая кросс-tenant путаница в UI
 * (документ, имя, отдел от одной организации, данные от другой). Fail-closed
 * на границе (035): контекст отбрасывается и замены ждём от host'а.
 *
 * Сравнение регистронезависимое: `orgId` в СЭД — не UUID, а строковый
 * идентификатор, и регистр в нём не является частью значения.
 */
export function checkTenantConsistency(context: SedContext): 'ok' | 'unknown' | 'mismatch' {
  const normalize = (value: string): string => value.trim().toLowerCase();
  const tenant = normalize(context.scope.tenantId);
  if (tenant.length === 0) return 'mismatch';
  if (normalize(context.user.orgId) !== tenant) return 'mismatch';
  const claimed = tokenTenantId(context.token);
  if (claimed === null) return 'unknown';
  return normalize(claimed) === tenant ? 'ok' : 'mismatch';
}

/** Закрытый перечень ключей разделов — источник истины для `NavigateAction.view`. */
const SED_VIEW_KEYS: readonly SedViewKey[] = ['home', 'my_documents', 'my_tasks'];

/**
 * Валидирует действие на стороне СЭД.
 *
 * Симметрично `isSedContext`: host получает `CustomEvent` со страницы, куда
 * может писать кто угодно, поэтому разбор detail — только через эту проверку,
 * а не через `as AssistantAction`.
 */
export function isAssistantAction(value: unknown): value is AssistantAction {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as {
    action?: unknown;
    documentId?: unknown;
    view?: unknown;
    query?: unknown;
  };
  switch (candidate.action) {
    case 'open_document':
      return typeof candidate.documentId === 'string' && candidate.documentId.trim().length > 0;
    case 'navigate':
      return SED_VIEW_KEYS.includes(candidate.view as SedViewKey);
    case 'search':
      return typeof candidate.query === 'string' && candidate.query.trim().length > 0;
    default:
      return false;
  }
}
