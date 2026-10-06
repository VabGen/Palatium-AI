import { HttpResponse, http } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';

import { ApiError, fetchDialogTurns, processIntent } from '../../src/api/client';
import { setAuthToken, setRuntimeMode } from '../../src/runtime/auth';
import { TRACE_HEADER } from '../../src/lib/trace';
import { server } from '../msw';
import type { DialogTurnResponse, FormatterTaskResult } from '../../src/types/contentDocument';

/**
 * HTTP-граница клиента (084) — интеграционный слой: MSW перехватывает реальный
 * `fetch`, поэтому проверяются именно те запросы, которые ушли бы из браузера.
 *
 * Здесь живут три класса багов, которые «тест на мок-клиенте» не поймал бы:
 *  - ретрай 5xx и его цена (сколько попыток реально ушло);
 *  - 401 → ОДИН refresh и один повтор (иначе цикл «401 → refresh → 401 → …»);
 *  - человекочитаемый текст 422 и статус отдельным полем (ApiError.status),
 *    потому что решение о поведении принимается по статусу, а не по подстроке.
 *
 * Ретраи намеренно идут РЕАЛЬНЫМ временем: задержки клиента (300/600 мс) — часть
 * контракта (backoff), и на fake-таймерах проверялся бы не он, а сам мок таймеров.
 * Плата — ~1 с на тест; дешевле, чем недетерминированный «зелёный» CI.
 */

const RESULT: FormatterTaskResult = {
  task_id: 'task-1',
  agent_role: 'formatter',
  status: 'success',
  confidence: 0.9,
  requires_review: false,
  error: null,
  output: null,
  hitl_cards: [],
};

const PROCESS_URL = '*/api/intents/process';

beforeEach(() => {
  setRuntimeMode('standalone');
  setAuthToken('tok-1');
});

describe('processIntent', () => {
  it('sends bearer and trace headers and returns the parsed result', async () => {
    let seen: Headers | null = null;
    server.use(
      http.post(PROCESS_URL, ({ request }) => {
        seen = request.headers;
        return HttpResponse.json(RESULT);
      })
    );

    await expect(processIntent('привет', 'th-1')).resolves.toEqual(RESULT);

    expect(seen!.get('Authorization')).toBe('Bearer tok-1');
    expect(seen!.get(TRACE_HEADER)).toBeTruthy();
    expect(seen!.get('Content-Type')).toBe('application/json');
  });

  it.each([
    ['empty text', ''],
    ['text over the server limit', 'a'.repeat(32_001)],
  ])('rejects %s client-side without sending a request', async (_label, text) => {
    let calls = 0;
    server.use(
      http.post(PROCESS_URL, () => {
        calls += 1;
        return HttpResponse.json(RESULT);
      })
    );

    await expect(processIntent(text, 'th-1')).rejects.toThrow();
    // Запрос, который сервер гарантированно отклонит (422), не должен уходить:
    // это не оптимизация, а отсутствие мусора в метриках и трассировке.
    expect(calls).toBe(0);
  });

  it('rejects more attachments than the server accepts, without sending a request', async () => {
    let calls = 0;
    server.use(
      http.post(PROCESS_URL, () => {
        calls += 1;
        return HttpResponse.json(RESULT);
      })
    );

    await expect(
      processIntent('привет', 'th-1', null, null, ['1', '2', '3', '4', '5', '6'])
    ).rejects.toThrow();
    expect(calls).toBe(0);
  });

  it('carries the status on the error and humanizes a 422 payload', async () => {
    server.use(
      http.post(PROCESS_URL, () =>
        HttpResponse.json(
          {
            detail: [
              { field: 'text', code: 'too_long', message: '«text»: максимум 32000 символов' },
            ],
          },
          { status: 422 }
        )
      )
    );

    const error = await processIntent('привет', 'th-1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    // Статус — отдельное поле: по тексту сервера решение принимать нельзя.
    expect((error as ApiError).status).toBe(422);
    expect((error as ApiError).message).toContain('максимум 32000 символов');
  });

  it.each([
    ['a plain HTTPException detail', { detail: 'thread not found' }, 'thread not found'],
    ['a prepared server issue', { detail: { message: 'карточка истекла' } }, 'карточка истекла'],
    ['a non-JSON body', 'gateway timeout', 'gateway timeout'],
  ])('surfaces %s as the error message', async (_label, body, expected) => {
    server.use(
      http.post(PROCESS_URL, () =>
        HttpResponse.text(typeof body === 'string' ? body : JSON.stringify(body), { status: 400 })
      )
    );

    const error = await processIntent('привет', 'th-1').catch((e: unknown) => e);

    expect((error as ApiError).status).toBe(400);
    expect((error as ApiError).message).toBe(expected);
  });

  it('retries a 5xx and succeeds on a later attempt', async () => {
    let attempts = 0;
    server.use(
      http.post(PROCESS_URL, () => {
        attempts += 1;
        return attempts < 3
          ? HttpResponse.text('upstream unavailable', { status: 503 })
          : HttpResponse.json(RESULT);
      })
    );

    await expect(processIntent('привет', 'th-1')).resolves.toEqual(RESULT);
    expect(attempts).toBe(3);
  });

  it('reports the server reason once the retries are exhausted', async () => {
    let attempts = 0;
    server.use(
      http.post(PROCESS_URL, () => {
        attempts += 1;
        return HttpResponse.text('upstream unavailable', { status: 502 });
      })
    );

    const error = await processIntent('привет', 'th-1').catch((e: unknown) => e);

    // Безадресное «запрос не выполнен» здесь было бы хуже: причина пришла с сервера.
    expect((error as ApiError).status).toBe(502);
    expect((error as ApiError).message).toBe('upstream unavailable');
    expect(attempts).toBe(3);
  });

  it('does not retry a 4xx — a rejected request stays rejected', async () => {
    let attempts = 0;
    server.use(
      http.post(PROCESS_URL, () => {
        attempts += 1;
        return HttpResponse.json({ detail: 'bad request' }, { status: 400 });
      })
    );

    await expect(processIntent('привет', 'th-1')).rejects.toThrow('bad request');
    expect(attempts).toBe(1);
  });
});

describe('401 handling', () => {
  it('mints a dev token once and retries the request exactly once', async () => {
    let tokenCalls = 0;
    let processCalls = 0;
    server.use(
      http.post('*/api/auth/dev-token', () => {
        tokenCalls += 1;
        return HttpResponse.json({ access_token: 'fresh' });
      }),
      http.post(PROCESS_URL, ({ request }) => {
        processCalls += 1;
        return request.headers.get('Authorization') === 'Bearer fresh'
          ? HttpResponse.json(RESULT)
          : new HttpResponse(null, { status: 401 });
      })
    );

    await expect(processIntent('привет', 'th-1', 'user-1')).resolves.toEqual(RESULT);

    expect(tokenCalls).toBe(1);
    expect(processCalls).toBe(2);
  });

  it('does not loop when the refreshed token is rejected too', async () => {
    let tokenCalls = 0;
    let attempts = 0;
    server.use(
      http.post('*/api/auth/dev-token', () => {
        tokenCalls += 1;
        return HttpResponse.json({ access_token: 'fresh' });
      }),
      http.post(PROCESS_URL, () => {
        attempts += 1;
        return new HttpResponse(null, { status: 401 });
      })
    );

    const error = await processIntent('привет', 'th-1', 'user-1').catch((e: unknown) => e);

    expect((error as ApiError).status).toBe(401);
    // Ровно один повтор после refresh и ни одного сверх: 401 НЕ входит в набор
    // ретраев с backoff, поэтому счётчик равен двум (исходный вызов + повтор), и
    // второй 401 завершает запрос, а не запускает новый refresh-цикл.
    expect(attempts).toBe(2);
    expect(tokenCalls).toBe(1);
  });
});

describe('fetchDialogTurns', () => {
  it('treats a 404 thread as an empty dialog, not as an error', async () => {
    server.use(
      http.get('*/api/sessions/th-1/turns', () => new HttpResponse(null, { status: 404 }))
    );

    await expect(fetchDialogTurns('th-1')).resolves.toEqual([]);
  });

  it('unwraps the items envelope', async () => {
    const turn: DialogTurnResponse = {
      thread_id: 'th-1',
      role: 'user',
      content: 'привет',
      seq: 0,
    };
    server.use(http.get('*/api/sessions/th-1/turns', () => HttpResponse.json({ items: [turn] })));

    await expect(fetchDialogTurns('th-1')).resolves.toEqual([turn]);
  });
});
