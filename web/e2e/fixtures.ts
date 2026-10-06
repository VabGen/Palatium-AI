/**
 * Фикстуры E2E: полезные нагрузки API, запуск виджета и чтение Shadow DOM.
 *
 * Тела ответов повторяют схемы `src/types/contentDocument.ts` и
 * `src/api/client.ts` — если контракт изменится, падение произойдёт здесь, а не
 * «где-то в UI». Никаких «примерных» ответов: только поля, которые реально
 * объявлены в типах.
 */
import type { Page } from '@playwright/test';
import { en, ru } from '../src/i18n/messages';
import type {
  ContentDocument,
  DialogTurnResponse,
  FormatterTaskResult,
  HITLCardView,
} from '../src/types/contentDocument';
import { MockServer } from './mock-server';
import type { AttachmentResponse } from '../src/api/client';

/** Тег элемента; контракт — `custom-elements.json`, здесь он же как константа теста. */
export const ASSISTANT = 'palatium-assistant';

/** Идентификатор вложения в моках: по нему строятся URL `content`/`complete`. */
export const ATTACHMENT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
export const CARD_ID = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';

/**
 * Тело загружаемого файла: содержимое не важно, важны размер и признак «поток
 * байт, а не JSON». Экспортируется, чтобы проверка размера в тесте не дублировала
 * литерал и не разъезжалась с фикстурой.
 */
export const E2E_PDF_BYTES = Buffer.from('%PDF-1.4 e2e');

// ────────────────────────────────────────────────────────────────────────────
// Payload builders
// ────────────────────────────────────────────────────────────────────────────

export function answerDocument(text = 'Готово: черновик письма во вложении.'): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: 'Черновик ответа',
    blocks: [
      { type: 'paragraph', text },
      { type: 'kv', items: [{ label: 'Адресат', value: 'Канцелярия' }] },
    ],
    actions: [],
    meta: { confidence: 0.92, requires_review: false, source_refs: [] },
  };
}

export function formatterResult(overrides: Partial<FormatterTaskResult> = {}): FormatterTaskResult {
  return {
    task_id: 'task-e2e',
    agent_role: 'formatter',
    status: 'success',
    confidence: 0.92,
    requires_review: false,
    error: null,
    output: answerDocument(),
    hitl_cards: [],
    ...overrides,
  };
}

/** Вложение готово к отправке: `status: 'ready'` проходит `refusalLabel` без причины отказа. */
export function readyAttachment(overrides: Partial<AttachmentResponse> = {}): AttachmentResponse {
  return {
    attachment_id: ATTACHMENT_ID,
    thread_id: null,
    filename: 'dogovor.pdf',
    mime_type: 'application/pdf',
    size_bytes: 2048,
    mode: 'attach',
    status: 'ready',
    page_count: 3,
    rejection_reason: null,
    error: null,
    created_at: '2026-09-29T12:00:00Z',
    expires_at: '2026-09-30T12:00:00Z',
    ...overrides,
  };
}

/** Ответ на `init`: `memory://` — хранилище без HTTP-фасада, байты идут через API. */
export function attachmentTicket(): {
  attachment_id: string;
  upload_url: string;
  expires_at: string;
  mode: string;
} {
  return {
    attachment_id: ATTACHMENT_ID,
    upload_url: `memory://items/${ATTACHMENT_ID}`,
    expires_at: '2026-09-29T13:00:00Z',
    mode: 'attach',
  };
}

/** Байты приняты, но пайплайн ещё не отработал (`complete` вернёт финальный статус). */
export function uploadedAttachment(filename = 'dogovor.pdf'): AttachmentResponse {
  return readyAttachment({
    filename,
    status: 'uploaded',
    page_count: null,
    expires_at: null,
  });
}

/** Отказ пайплайна: файл дошёл до сервера и был отклонён (не «тихо исчез»). */
export function quarantinedAttachment(
  rejectionReason: NonNullable<AttachmentResponse['rejection_reason']>,
  filename = 'virus.pdf'
): AttachmentResponse {
  return readyAttachment({
    filename,
    status: 'quarantined',
    page_count: null,
    rejection_reason: rejectionReason,
  });
}

export function choiceCard(overrides: Partial<HITLCardView> = {}): HITLCardView {
  return {
    card_id: CARD_ID,
    thread_id: 'thread-e2e',
    task_id: 'task-e2e',
    purpose: 'user_choice',
    title: 'Какой тон письма выбрать?',
    body: 'Ответ уйдёт внешнему адресату.',
    options: [
      {
        action_id: 'formal',
        label: 'Официальный',
        kind: 'custom',
        style: 'primary',
        action_token: 'tok-formal',
      },
      {
        action_id: 'short',
        label: 'Короткий',
        kind: 'custom',
        style: 'secondary',
        action_token: 'tok-short',
      },
    ],
    risk_score: 0.2,
    status: 'pending',
    created_at: '2026-09-29T12:00:00Z',
    expires_at: '2026-09-29T12:30:00Z',
    ...overrides,
  };
}

/** Карточка инструмента: `mcp_tool_approval` — единственный путь через step-up. */
export function toolCard(overrides: Partial<HITLCardView> = {}): HITLCardView {
  return {
    ...choiceCard(),
    purpose: 'mcp_tool_approval',
    title: 'Отправить письмо через EDMS?',
    body: 'Необратимая операция: письмо уйдёт адресату.',
    risk_score: 0.81,
    options: [
      {
        action_id: 'send',
        label: 'Отправить',
        kind: 'approve',
        style: 'primary',
        action_token: 'tok-send',
      },
    ],
    ...overrides,
  };
}

export function stepUpChallenge(): {
  required: boolean;
  method: string;
  required_acr: string;
  card_claim: string;
  challenge: string;
  authorize_url: null;
  assertion: null;
} {
  return {
    required: true,
    method: 'idp_acr',
    required_acr: 'urn:mace:incommon:iap:silver',
    card_claim: 'hitl_card_id',
    challenge: 'nonce-42',
    authorize_url: null,
    assertion: null,
  };
}

export function resolvedCard(actionId = 'formal'): HITLCardView {
  return { ...choiceCard(), status: 'resolved', resolved_action_id: actionId };
}

export function dialogTurn(
  role: 'user' | 'assistant',
  content: string,
  seq: number
): DialogTurnResponse {
  return { thread_id: 'thread-e2e', role, content, seq };
}

// ────────────────────────────────────────────────────────────────────────────
// Mock server setup
// ────────────────────────────────────────────────────────────────────────────

/**
 * Минимальный набор ответов, без которого виджет не стартует: выпуск dev-токена
 * и пустая история диалога. Все остальные эндпоинты тест объявляет сам —
 * забытый мок упадёт как 404 и попадёт в `unmatched`.
 */
export function defaultApi(): MockServer {
  const server = new MockServer();
  server.always('auth.dev-token', { json: { access_token: 'e2e-token' } });
  server.always('sessions.turns', { json: { items: [] } });
  return server;
}

/**
 * Сокет сессии — заглушка, а не реальное соединение.
 *
 * Сервер подписки отвечает сразу, поэтому бейдж `WS` в шапке появляется
 * детерминированно; `ping` получает `pong`, чтобы пинг-таймер не копил ошибки.
 * `onUrl` отдаёт адрес подключения: по нему проверяется, что REST и сокет уходят
 * на один origin (контракт топологии — см. `endpoints.spec.ts`).
 */
export async function stubSessionSocket(page: Page, onUrl?: (url: string) => void): Promise<void> {
  await page.routeWebSocket(/\/ws\/sessions\//, socket => {
    onUrl?.(socket.url());
    socket.send(JSON.stringify({ type: 'session.subscribed', thread_id: 'e2e', trace_id: 'e2e' }));
    socket.onMessage(message => {
      if (message === 'ping') socket.send(JSON.stringify({ type: 'pong' }));
    });
  });
}

/**
 * Открыть стенд и дождаться апгрейда элемента.
 *
 * Счётчики (`__palatiumReady`, `__palatiumNavigations`) ставятся ДО загрузки:
 * `palatium:ready` летит из `connectedCallback`, и подписаться после `goto` уже
 * поздно. Тот же приём даёт проверку «виджет не перезагружает страницу СЭД»:
 * повторная навигация увеличила бы `__palatiumNavigations`.
 */
export async function openWidget(page: Page, url = '/standalone.html'): Promise<void> {
  await page.addInitScript(() => {
    const state = window as unknown as { __palatiumReady: number; __palatiumNavigations: number };
    state.__palatiumReady = 0;
    state.__palatiumNavigations =
      (state.__palatiumNavigations ?? 0) + (window.top === window ? 1 : 0);
    window.addEventListener(
      'palatium:ready',
      () => {
        state.__palatiumReady += 1;
      },
      { capture: true }
    );
  });
  await page.goto(url);
  await page.waitForFunction(
    () => (window as unknown as { __palatiumReady: number }).__palatiumReady > 0
  );
}

export async function readyCount(page: Page): Promise<number> {
  return page.evaluate(() => (window as unknown as { __palatiumReady: number }).__palatiumReady);
}

export async function navigationCount(page: Page): Promise<number> {
  return page.evaluate(
    () => (window as unknown as { __palatiumNavigations: number }).__palatiumNavigations
  );
}

/** Догрузить контекст СЭД (мок-хост стенда) и дождаться host-режима. */
export async function connectHost(page: Page): Promise<void> {
  await page.getByRole('button', { name: "Отправить контекст host'а" }).click();
  await page
    .locator(`${ASSISTANT}`)
    .getByText('автономно', { exact: true })
    .waitFor({ state: 'detached' });
}

// ────────────────────────────────────────────────────────────────────────────
// Контекст СЭД для проверок границы доверия
// ────────────────────────────────────────────────────────────────────────────

/**
 * JWT с заданными claims — БЕЗ подписи.
 *
 * Подпись здесь не нужна и не проверяется: виджет не валидирует токен, он
 * сверяет tenant-claim с `scope.tenantId` (`checkTenantConsistency`), а проверка
 * подписи — работа бэкенда. Тест воспроизводит именно ту часть, что читает виджет.
 */
export function sedJwt(claims: Record<string, unknown>): string {
  const encode = (value: unknown): string =>
    Buffer.from(JSON.stringify(value)).toString('base64url');
  return `${encode({ alg: 'none', typ: 'JWT' })}.${encode(claims)}.e2e`;
}

/**
 * Контекст host'а для проверок несовпадений tenant'а и локали.
 *
 * `tokenOrgId: null` — токен без tenant-claim (dev-токен стенда): сверять нечего,
 * такой контекст обязан приниматься.
 * `localization` — значение enum СЭД как есть (включая `GE`, для которого у host'а
 * нет ресурсов): проверять откат языка нужно тем же путём, что и tenant.
 */
export function hostContextForTest(
  options: {
    orgId?: string;
    tenantId?: string;
    tokenOrgId?: string | null;
    localization?: 'RU' | 'EN' | 'GE';
    /**
     * Имя пользователя. `fullName` по умолчанию — как в СЭД (сначала фамилия),
     * а `firstName` задаётся отдельно: обращение строится только из него, чтобы
     * виджет не угадывал порядок слов (`preferredName` в контракте).
     */
    firstName?: string;
    fullName?: string;
    /**
     * Тред, который host уже ведёт (непрерывность диалога, W11-остаток).
     * Не задан — поля в контексте нет, как у host'а, который ещё не сохранил тред.
     */
    threadId?: string;
  } = {}
): Record<string, unknown> {
  const orgId = options.orgId ?? 'org-e2e';
  const tenantId = options.tenantId ?? orgId;
  const tokenOrgId = options.tokenOrgId === undefined ? tenantId : options.tokenOrgId;
  return {
    token: tokenOrgId === null ? 'e2e-token' : sedJwt({ sub: 'e2e-user', org_id: tokenOrgId }),
    user: {
      id: 'e2e-user',
      orgId,
      fullName: options.fullName ?? 'Петров Иван',
      ...(options.firstName === undefined ? {} : { firstName: options.firstName }),
      localization: options.localization ?? 'RU',
    },
    ...(options.threadId === undefined ? {} : { threadId: options.threadId }),
    scope: { tenantId, departmentIds: ['e2e-department'] },
  };
}

/** Отправить контекст так, как это делает СЭД: событием на `window`. */
export async function sendHostContext(page: Page, context: Record<string, unknown>): Promise<void> {
  await page.evaluate(detail => {
    window.dispatchEvent(new CustomEvent('sed:context-changed', { detail }));
  }, context);
}

/**
 * Записывает треды, которые виджет объявил событием `sed:thread-changed`.
 *
 * Подписка ставится ДО загрузки страницы (как счётчики `__palatiumReady`): часть
 * объявлений приходит сразу после рукопожатия, и подписаться после `goto` уже
 * поздно. Событие всплывает и проходит через границу Shadow DOM, поэтому слушаем
 * `window` — host в реальной интеграции делает то же.
 */
export async function trackThreadEvents(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const state = window as unknown as { __palatiumThreads: string[] };
    state.__palatiumThreads = [];
    window.addEventListener(
      'sed:thread-changed',
      (event: Event) => {
        const detail = (event as CustomEvent<{ threadId?: unknown }>).detail;
        if (typeof detail?.threadId === 'string') state.__palatiumThreads.push(detail.threadId);
      },
      { capture: true }
    );
  });
}

/** Треды, объявленные виджетом, в порядке объявления. */
export async function announcedThreads(page: Page): Promise<string[]> {
  return page.evaluate(
    () => (window as unknown as { __palatiumThreads: string[] }).__palatiumThreads
  );
}

// ────────────────────────────────────────────────────────────────────────────
// Shadow DOM reading
// ────────────────────────────────────────────────────────────────────────────

/**
 * Видимые пользователю строки виджета: текстовые узлы Shadow DOM плюс подписи,
 * которые читает скринридер (`aria-label`, `placeholder`, `title`).
 *
 * Скрытое (`display: none`) и `aria-hidden` исключаются: у свёрнутой панели есть
 * невидимые контролы, и «видимый текст» должен означать именно видимый.
 */
export async function visibleStrings(page: Page): Promise<string[]> {
  return page.evaluate(elementTag => {
    const root = document.querySelector(elementTag)?.shadowRoot;
    if (!root) return [];
    const hidden = (element: Element | null): boolean =>
      !element ||
      element.getClientRects().length === 0 ||
      element.closest('[aria-hidden="true"]') !== null;

    const strings: string[] = [];
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent?.replace(/\s+/g, ' ').trim() ?? '';
      if (text && !hidden(walker.currentNode.parentElement)) strings.push(text);
    }

    for (const element of root.querySelectorAll('[aria-label], [placeholder], [title]')) {
      if (hidden(element)) continue;
      for (const attribute of ['aria-label', 'placeholder', 'title']) {
        const value = element.getAttribute(attribute)?.trim();
        if (value) strings.push(value);
      }
    }
    return strings;
  }, ASSISTANT);
}

/**
 * Строки, которые остались английскими при `lang="ru"`.
 *
 * Сравнение идёт с ТЕМ ЖЕ словарём, что использует приложение (`src/i18n/messages.ts`),
 * поэтому проверка не устаревает при добавлении ключей: берётся английский текст,
 * который в русском отличается, и ищется его непереводимый префикс (часть до
 * первого `{param}`). Ключи, где RU и EN совпадают (`Palatium`, `DEV`, `IdP step-up JWT`),
 * исключены автоматически — это не «непереведённый текст», а одинаковый.
 */
export function findEnglishLeaks(samples: readonly string[]): string[] {
  const keys = Object.keys(ru) as (keyof typeof ru)[];
  const leaks = new Set<string>();

  for (const key of keys) {
    const english = en[key];
    const russian = ru[key];
    // Форматные ключи (`{used} / {limit}`) не несут прозы: сравнивать нечего.
    const prefix = english.split('{')[0].trim();
    if (prefix.length < 4) continue;
    if (russian.split('{')[0].trim() === prefix) continue;
    for (const sample of samples) {
      if (sample.includes(prefix)) leaks.add(`${key}: ${JSON.stringify(prefix)}`);
    }
  }
  return [...leaks].sort();
}
