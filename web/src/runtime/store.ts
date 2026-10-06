/**
 * Runtime-состояние виджета: контекст СЭД, идентификаторы запроса, локаль.
 *
 * Внешний store (а не React Context) выбран осознанно: контекст приходит из
 * imperative-кода — `CustomEvent` на `window` — то есть снаружи React-дерева.
 * `useSyncExternalStore` даёт корректную подписку без «мостов» через refs.
 *
 * Идентификаторы (`threadId`, standalone `userId`/`orgId`) живут в памяти:
 * storage запрещён (план §4.1, гейт «ноль storage под токен/тред»).
 */
import { normalizeThreadId, preferredName, toBcp47, type SedContext } from '@palatium/contract';
import { setI18nLocale } from '../i18n';
import { setAuthToken, setRuntimeMode, type RuntimeMode } from './auth';

/** Статус рукопожатия с host'ом. `pending` — ждём ответа, окно 500 мс (план §2.2). */
export type HostStatus = 'pending' | 'connected' | 'standalone';

export interface AssistantRuntime {
  readonly mode: RuntimeMode;
  readonly hostStatus: HostStatus;
  /** Контекст СЭД; `null` — host ещё не ответил или виджет запущен автономно. */
  readonly context: SedContext | null;
  /** `user.id` из контекста либо сгенерированный id standalone-сессии. */
  readonly userId: string;
  /** Tenant: `scope.tenantId` из контекста либо standalone-значение по умолчанию. */
  readonly orgId: string;
  /** Тред диалога в памяти сессии. */
  readonly threadId: string;
  /**
   * `true` — текущий `threadId` пришёл от host'а в контексте.
   *
   * Виджет объявляет тред событием `sed:thread-changed` только тогда, когда
   * создал его сам: сообщать host'у id, который он сам же и прислал, — лишний
   * трафик и ложное «сменился тред» в его обработчике.
   */
  readonly threadFromHost: boolean;
  /** BCP-47 для форматирования дат/чисел. */
  readonly locale: string;
  /**
   * Имя для обращения; `null` — host его не дал (автономный режим или контекст
   * без имени). Считается из контекста, а не хранится отдельным состоянием:
   * второй источник того же имени разошёлся бы с первым.
   */
  readonly userName: string | null;
  /** Панель развёрнута. Лончер показывается при `false` (см. `widget.css`). */
  readonly panelOpen: boolean;
}

/**
 * `ru-RU` — «страховка» в двух разных случаях, и оба ведут к языку host'а:
 *
 * 1. Контекст есть, но `localization` не отображается в BCP-47 (`GE`): СЭД сам
 *    рендерит для него RU (`frontend/gtb/src/i18n.js`, `fallbackLng: RUS_LANGUAGE`),
 *    и виджет обязан показать тот же язык. Язык браузера здесь — не аргумент:
 *    внутри чужой страницы он чужой и разъехался бы с интерфейсом вокруг (`§5 п.3`).
 * 2. Контекста нет вовсе и браузер не сообщил язык (standalone/dev).
 */
const FALLBACK_LOCALE = 'ru-RU';
const STANDALONE_ORG = 'org-default';

function randomId(prefix: string): string {
  return `${prefix}-${crypto.randomUUID()}`;
}

interface MutableState {
  mode: RuntimeMode;
  hostStatus: HostStatus;
  context: SedContext | null;
  threadId: string;
  /** Текущий тред создан host'ом (см. `AssistantRuntime.threadFromHost`). */
  threadFromHost: boolean;
  standaloneUserId: string;
  orgId: string;
  /** Явный `lang`-атрибут элемента — приоритетнее локализации из контекста. */
  langOverride: string | null;
  panelOpen: boolean;
}

const state: MutableState = {
  mode: 'standalone',
  hostStatus: 'pending',
  context: null,
  threadId: randomId('thread'),
  threadFromHost: false,
  standaloneUserId: randomId('user'),
  orgId: STANDALONE_ORG,
  langOverride: null,
  panelOpen: true,
};

const listeners = new Set<() => void>();

function resolveLocale(): string {
  if (state.langOverride) return state.langOverride;
  const localization = state.context?.user.localization;
  // Host ДАЛ локализацию — значит язык интерфейса известен ему; браузер не спрашиваем.
  if (localization !== undefined) return toBcp47(localization) ?? FALLBACK_LOCALE;
  return navigator.language || FALLBACK_LOCALE;
}

function buildSnapshot(): AssistantRuntime {
  const context = state.context;
  return {
    mode: state.mode,
    hostStatus: state.hostStatus,
    context,
    userId: context?.user.id ?? state.standaloneUserId,
    orgId: context?.scope.tenantId ?? state.orgId,
    threadId: state.threadId,
    threadFromHost: state.threadFromHost,
    locale: resolveLocale(),
    userName: preferredName(context?.user),
    panelOpen: state.panelOpen,
  };
}

let snapshot: AssistantRuntime = buildSnapshot();

function publish(): void {
  snapshot = buildSnapshot();
  // Локаль — источник и для форматирования чисел, и для словарей: держим их вместе,
  // чтобы `t()` вне React (client.ts) не расходился с UI.
  setI18nLocale(snapshot.locale);
  for (const listener of [...listeners]) listener();
}

export function subscribeRuntime(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Стабильная ссылка между изменениями — требование `useSyncExternalStore`. */
export function getRuntimeSnapshot(): AssistantRuntime {
  return snapshot;
}

/** Актуализирует словари при инициализации модуля (до первого `publish`). */
setI18nLocale(snapshot.locale);

/** Принимает контекст от host'а: обновляет состояние и переводит виджет в host-режим. */
export function applyHostContext(context: SedContext): void {
  state.context = context;
  state.hostStatus = 'connected';
  state.mode = 'host';
  state.orgId = context.scope.tenantId;
  setRuntimeMode('host');
  setAuthToken(context.token);
  adoptHostThread(context.threadId);
  publish();
}

/**
 * Продолжает тред, который host уже ведёт (перезагрузка страницы СЭД).
 *
 * Контекст без `threadId` тред НЕ сбрасывает: host вправе слать его часто (смена
 * документа, перерисовка) и не обязан каждый раз повторять тред. Сброс — только
 * явный «Новый диалог» (`startNewThread`).
 */
function adoptHostThread(threadId: SedContext['threadId']): void {
  const next = normalizeThreadId(threadId);
  if (next === null) return;
  state.threadId = next;
  state.threadFromHost = true;
}

/** Host не ответил в отведённое окно — виджет работает автономно (ограниченный функционал). */
export function markStandalone(): void {
  if (state.hostStatus !== 'pending') return;
  state.hostStatus = 'standalone';
  publish();
}

/** Новый тред без перезагрузки страницы host'а. */
export function startNewThread(): void {
  state.threadId = randomId('thread');
  state.threadFromHost = false;
  publish();
}

/** `lang`-атрибут элемента: задаёт локаль форматирования поверх контекста. */
export function setLangOverride(lang: string | null): void {
  state.langOverride = lang && lang.trim().length > 0 ? lang.trim() : null;
  publish();
}

/** Развернуть/свернуть панель. Лончер и `[collapsed]` на хосте — производные. */
export function setPanelOpen(open: boolean): void {
  if (state.panelOpen === open) return;
  state.panelOpen = open;
  publish();
}
