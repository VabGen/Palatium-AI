/**
 * Мок HTTP/WS-границы виджета для E2E (W8).
 *
 * Перехватываются только `/api/**` и `/ws/sessions/**`: тесты не поднимают
 * backend и не зависят от его состояния. Каждый незамоканный вызов `/api/**`
 * фиксируется в `unmatched` — тест сам решает, считать ли это ошибкой (в
 * `state-matrix.spec.ts` это обязательная проверка: виджет не должен ходить в
 * неизвестные эндпоинты).
 */
import type { Page } from '@playwright/test';

/** Один сценарный ответ. Очередь из них позволяет «сначала 401, потом 200». */
export type Reply = {
  status?: number;
  /** JSON-тело; взаимоисключающе с `text`. */
  json?: unknown;
  /** Сырое тело (422-детали, HTML-ошибка шлюза). */
  text?: string;
  contentType?: string;
  /**
   * Задержка перед ответом — окно, в котором UI обязан показать pending-состояние
   * (`state-matrix.ts`, кадр `pending`). Без неё «индикатор работы» нечем проверить.
   */
  delayMs?: number;
};

/** Зафиксированный вызов: по нему проверяются заголовки, тело и состав запросов. */
export type ApiCall = {
  /** Ключ эндпоинта из `ROUTES`, например `intents.process`. */
  key: string;
  method: string;
  path: string;
  body: unknown;
  /** Размер тела в байтах — для `PUT` вложений тело бинарное, JSON не парсится. */
  bytes: number;
  authorization: string | null;
  traceId: string | null;
  /**
   * `x-organization` либо `null`. Поле существует ради ПРОВЕРКИ ОТСУТСТВИЯ:
   * виджет обязан слать `null` всегда. Tenant и права берутся бэкендом из
   * валидированного JWT-claim (`principal.org_id`), а `org_id` в теле запроса
   * игнорируется роутером; заголовок-дубль создал бы иллюзию, что клиент решает,
   * какой tenant обслуживать (020, Zero Trust). Проверка — `interaction.spec.ts`.
   */
  tenantHeader: string | null;
};

type RouteSpec = { key: string; method: string; pattern: RegExp };

/**
 * Закрытый перечень эндпоинтов, которые виджет имеет право вызывать.
 * Список сверен с `src/api/client.ts`; новый вызов без строки здесь = 404 и
 * запись в `unmatched`, то есть тест упадёт — это и есть желаемое поведение.
 */
const ROUTES: readonly RouteSpec[] = [
  { key: 'auth.dev-token', method: 'POST', pattern: /^\/auth\/dev-token$/ },
  { key: 'sessions.turns', method: 'GET', pattern: /^\/sessions\/[^/]+\/turns$/ },
  { key: 'intents.process', method: 'POST', pattern: /^\/intents\/process$/ },
  { key: 'hitl.card', method: 'GET', pattern: /^\/hitl\/[^/]+$/ },
  { key: 'hitl.step-up', method: 'POST', pattern: /^\/hitl\/[^/]+\/step-up-challenge$/ },
  { key: 'hitl.respond', method: 'POST', pattern: /^\/hitl\/[^/]+\/respond$/ },
  { key: 'memory.save', method: 'POST', pattern: /^\/memory\/save$/ },
  { key: 'memory.forget', method: 'POST', pattern: /^\/memory\/forget$/ },
  { key: 'memory.extract', method: 'POST', pattern: /^\/memory\/extract$/ },
  { key: 'attachments.init', method: 'POST', pattern: /^\/attachments\/init$/ },
  { key: 'attachments.content', method: 'PUT', pattern: /^\/attachments\/[^/]+\/content$/ },
  { key: 'attachments.complete', method: 'POST', pattern: /^\/attachments\/[^/]+\/complete$/ },
  { key: 'attachments.delete', method: 'DELETE', pattern: /^\/attachments\/[^/]+$/ },
  { key: 'feedback', method: 'POST', pattern: /^\/feedback$/ },
  { key: 'documents.pdf', method: 'POST', pattern: /^\/documents\/export\/pdf$/ },
];

/** Ответ на незамоканный вызов: упасть тестом «виджет ходит мимо контракта». */
const UNMATCHED: Reply = { status: 404, json: { detail: 'e2e: endpoint is not mocked' } };

export class MockServer {
  /** Все вызовы в порядке поступления — для проверки тела, токена и счётчиков. */
  readonly calls: ApiCall[] = [];
  /** Вызовы, для которых не нашлось ни сценария, ни строки в `ROUTES`. */
  readonly unmatched: ApiCall[] = [];

  readonly #scripted = new Map<string, Reply[]>();
  readonly #fallback = new Map<string, Reply>();

  /**
   * Задать ответ(ы) для эндпоинта.
   *
   * Очередь расходуется по одному ответу на вызов; последний повторяется, поэтому
   * `reply('intents.process', {status: 401}, {json: answer})` = «первый вызов
   * истёк, второй успешен», а `reply(key, {json})` = «всегда так».
   */
  reply(key: string, ...replies: Reply[]): this {
    if (replies.length === 0) throw new Error(`reply(${key}): нужен хотя бы один ответ`);
    this.#fallback.delete(key);
    this.#scripted.set(key, [...replies]);
    return this;
  }

  /** Ответ по умолчанию — та же очередь, но семантически «и так всегда». */
  always(key: string, reply: Reply): this {
    this.#fallback.set(key, reply);
    return this;
  }

  callsTo(key: string): ApiCall[] {
    return this.calls.filter(call => call.key === key);
  }

  /** Последний вызов эндпоинта либо `null` — читается в проверках «тело запроса такое». */
  lastCall(key: string): ApiCall | null {
    return this.callsTo(key).at(-1) ?? null;
  }

  async install(page: Page): Promise<void> {
    // Матч по ПРЕФИКСУ пути, а не глобом `**/api/**`: тот же глоб ловил
    // `/src/api/client.ts` (модуль самого виджета) и отдавал ему 404 — стенд
    // переставал грузиться, а падал бы «непонятно почему» тест любого кадра.
    await page.route(
      url => url.pathname.startsWith('/api/'),
      async route => {
        const request = route.request();
        const url = new URL(request.url());
        const path = url.pathname.replace(/^\/api/, '');
        const method = request.method();
        const spec = ROUTES.find(route => route.method === method && route.pattern.test(path));

        const call: ApiCall = {
          key: spec?.key ?? `unmatched ${method} ${path}`,
          method,
          path,
          body: safeJson(request.postData()),
          bytes: request.postDataBuffer()?.byteLength ?? 0,
          authorization: request.headers()['authorization'] ?? null,
          traceId: request.headers()['x-trace-id'] ?? null,
          tenantHeader: request.headers()['x-organization'] ?? null,
        };
        this.calls.push(call);
        if (!spec) this.unmatched.push(call);

        const reply = spec ? this.#resolve(spec.key) : UNMATCHED;
        if (reply.delayMs) await new Promise(resolve => setTimeout(resolve, reply.delayMs));
        await route.fulfill(toFulfill(reply));
      }
    );
  }

  #resolve(key: string): Reply {
    const queue = this.#scripted.get(key);
    if (queue && queue.length > 0) {
      // Последний ответ держится до конца теста: «дальше всегда успех».
      return queue.length === 1 ? queue[0] : (queue.shift() as Reply);
    }
    return this.#fallback.get(key) ?? UNMATCHED;
  }
}

function safeJson(body: string | null): unknown {
  if (body === null || body.length === 0) return null;
  try {
    return JSON.parse(body) as unknown;
  } catch {
    // Бинарное/не-JSON тело (PUT файла) — оставляем как есть, размер уже известен.
    return body;
  }
}

function toFulfill(reply: Reply): {
  status: number;
  json?: unknown;
  body?: string;
  contentType?: string;
} {
  const status = reply.status ?? 200;
  if (reply.text !== undefined) {
    return {
      status,
      body: reply.text,
      contentType: reply.contentType ?? 'text/plain; charset=utf-8',
    };
  }
  return { status, json: reply.json ?? {} };
}
