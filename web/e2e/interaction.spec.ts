/**
 * Проводной контракт виджета (W8): что реально уходит на сервер и что происходит
 * при сбоях. Матрица состояний проверяет то, что видит пользователь; здесь —
 * тела запросов, заголовки, повторы и обновление токена.
 *
 * Ни один тест не открывает страницу заново: перезагрузка страницы СЭД — то, что
 * виджет не имеет права делать (план §4.1), поэтому счётчик навигаций проверяется
 * и в happy path, и в ветке 401.
 */
import { expect, test, type Page } from '@playwright/test';
import {
  ATTACHMENT_ID,
  CARD_ID,
  E2E_PDF_BYTES,
  answerDocument,
  choiceCard,
  connectHost,
  defaultApi,
  navigationCount,
  openWidget,
  readyCount,
  stubSessionSocket,
} from './fixtures';
import type { Reply } from './mock-server';

/** Отправить сообщение так, как это делает человек: ввод + Enter-подобный клик. */
async function ask(page: Page, text: string): Promise<void> {
  await page.getByRole('textbox').fill(text);
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
}

function answer(): Reply {
  return { json: { task_id: 'task-1', output: answerDocument() } };
}

/**
 * Дождаться готового ответа, а не плейсхолдера «печатает».
 *
 * Пока запрос в работе, в ленте уже висит `.msg.assistant.pending` — проверка
 * «есть один `.msg.assistant`» проходит на нём, и следующий за ней подсчёт вызовов
 * ловит гонку (запрос ещё не ушёл). Ждём именно не-pending сообщение.
 */
async function expectAnswer(page: Page): Promise<void> {
  await expect(page.locator('.msg.assistant:not(.pending)')).toHaveCount(1);
}

test.describe('запросы к API', () => {
  test('intent уходит с токеном, trace-id и идентификатором треда', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await ask(page, 'Составь письмо');

    const call = server.lastCall('intents.process');
    expect(call).not.toBeNull();
    expect(call?.body).toMatchObject({ text: 'Составь письмо' });
    // `thread_id` — не пустая строка: тред живёт в памяти сессии, а не в URL.
    expect(String((call?.body as { thread_id?: string }).thread_id ?? '')).not.toBe('');
    expect(call?.authorization).toMatch(/^Bearer /);
    // Корреляция обязательна на каждом вызове (040): без заголовка трасса рвётся.
    expect(call?.traceId).toBeTruthy();
  });

  /**
   * Tenant и права — не дело клиента (020, Zero Trust).
   *
   * Соблазн передать их заголовком возникает при первой же интеграции («а как
   * сервер узнает организацию?»), и тогда клиентский заголовок станет тихим
   * вторым источником правды рядом с JWT. Проверка держит контракт: сервер берёт
   * `org_id` из валидированного claim, `SedContext.permissions` виджетом не
   * передаётся никуда (см. §9.4 `docs/embedded-assistant.md`).
   */
  test('tenant и права не передаются заголовками — их определяет токен', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);
    await connectHost(page);

    await ask(page, 'Покажи мои поручения');
    await expectAnswer(page);

    expect(server.calls.length).toBeGreaterThan(0);
    for (const call of server.calls) {
      expect(
        call.tenantHeader,
        `${call.method} ${call.path}: x-organization не отправляется`
      ).toBeNull();
    }
  });

  test('вложение уходит через API, если хранилище не имеет HTTP-адреса', async ({ page }) => {
    const server = defaultApi();
    const uploaded = {
      attachment_id: ATTACHMENT_ID,
      filename: 'dogovor.pdf',
      mime_type: 'application/pdf',
      size_bytes: E2E_PDF_BYTES.byteLength,
      mode: 'attach',
      status: 'uploaded',
      page_count: null,
      rejection_reason: null,
      error: null,
      thread_id: null,
      created_at: '2026-09-29T12:00:00Z',
      expires_at: null,
    };
    server.reply('attachments.init', {
      json: {
        attachment_id: ATTACHMENT_ID,
        // `memory://` — признак хранилища без HTTP-фасада: байты идут через API.
        upload_url: `memory://items/${ATTACHMENT_ID}`,
        expires_at: '2026-09-29T13:00:00Z',
        mode: 'attach',
      },
    });
    server.reply('attachments.content', { json: uploaded });
    server.reply('attachments.complete', { json: { ...uploaded, status: 'ready', page_count: 3 } });
    server.reply('intents.process', answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.locator('input[type=file]').setInputFiles({
      name: 'dogovor.pdf',
      mimeType: 'application/pdf',
      buffer: E2E_PDF_BYTES,
    });
    await page.locator('.attachment-chip.is-ready').waitFor();
    await ask(page, 'Что в договоре?');

    const upload = server.lastCall('attachments.content');
    // Байты считаем от той же фикстуры, что и подставили: литерал в проверке
    // разъехался бы с телом файла при первой же правке (075).
    expect(upload?.bytes).toBe(E2E_PDF_BYTES.byteLength);
    expect(server.callsTo('attachments.complete')).toHaveLength(1);
    // Файл попадает в ход как `attachment_ids`, а не как текст промпта.
    expect(server.lastCall('intents.process')?.body).toMatchObject({
      attachment_ids: [ATTACHMENT_ID],
    });
  });

  test('память мутируется только через HITL-карточку', async ({ page }) => {
    const server = defaultApi();
    server.reply('memory.save', { json: { ...choiceCard(), purpose: 'quality_review' } });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.getByRole('button', { name: 'Память' }).click();
    await page.locator('.memory-input').fill('pref-lang');
    await page.locator('.memory-textarea').fill('Общается по-русски');
    await page.getByRole('button', { name: 'Запросить сохранение' }).click();

    const call = server.lastCall('memory.save');
    // Пространство имён и владелец записи — из контекста, а не из формы.
    expect(call?.body).toMatchObject({
      entry_key: 'pref-lang',
      text: 'Общается по-русски',
      namespace_kind: 'user',
      memory_type: 'preference',
    });
    expect(String((call?.body as { scope_id?: string }).scope_id ?? '')).not.toBe('');
  });

  test('«Новый диалог» меняет thread_id без перезагрузки страницы', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', answer(), answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await ask(page, 'Первый вопрос');
    await expect(page.locator('.msg.assistant')).toHaveCount(1);
    const firstThread = (server.lastCall('intents.process')?.body as { thread_id: string })
      .thread_id;

    await page.getByRole('button', { name: 'Новый диалог' }).click();
    await expect(page.locator('.msg')).toHaveCount(0);
    await ask(page, 'Второй вопрос');
    await expect(page.locator('.msg.assistant')).toHaveCount(1);

    const secondThread = (server.lastCall('intents.process')?.body as { thread_id: string })
      .thread_id;
    expect(secondThread).not.toBe(firstThread);
    // Страница СЭД осталась той же: сброс треда — это состояние виджета.
    expect(await navigationCount(page)).toBe(1);
    expect(await readyCount(page)).toBe(1);
  });

  test('повторная генерация переиспользует исходный запрос', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', answer(), {
      json: { task_id: 'task-2', output: answerDocument('Второй вариант.') },
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await ask(page, 'Составь письмо');
    await page.getByRole('button', { name: 'Сформировать ответ заново' }).click();
    await expect(page.locator('.msg.assistant .block-paragraph')).toContainText('Второй вариант.');

    const calls = server.callsTo('intents.process');
    expect(calls).toHaveLength(2);
    expect((calls[1].body as { text: string }).text).toBe('Составь письмо');
    // Сообщение заменяется, а не добавляется: в транскрипте по-прежнему один ответ.
    await expect(page.locator('.msg.assistant')).toHaveCount(1);
  });

  test('оценка ответа уходит телом, которое ждёт бэкенд', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', answer());
    server.reply('feedback', { json: { status: 'ok' } });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await ask(page, 'Составь письмо');
    await page.getByRole('button', { name: 'Ответ полезен' }).click();

    const call = server.lastCall('feedback');
    expect(call?.body).toMatchObject({ feedback: 'like' });
    // Схема `FeedbackRequest` — `message_id: str`; на клиенте это id сообщения.
    expect(typeof (call?.body as { message_id?: unknown }).message_id).toBe('string');
  });
});

test.describe('сбои и токен', () => {
  test('5xx повторяется, но не молча: пользователь видит причину', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', { status: 503, json: { detail: 'LiteLLM недоступен' } });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await ask(page, 'Составь письмо');
    await expect(page.locator('.msg-error')).toContainText('LiteLLM недоступен');

    // Один запрос + два повтора с backoff: сеть/5xx ретраятся, 4xx — нет.
    expect(server.callsTo('intents.process')).toHaveLength(3);
  });

  test('401 обновляет токен и повторяет запрос один раз', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', { status: 401, json: { detail: 'token expired' } }, answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await ask(page, 'Составь письмо');
    await expectAnswer(page);

    // Первый mint при старте + повторный после 401: токен живёт только в памяти,
    // поэтому обновление — это новый выпуск, а не чтение из storage.
    expect(server.callsTo('auth.dev-token')).toHaveLength(2);
    expect(server.callsTo('intents.process')).toHaveLength(2);
    await expect(page.locator('.msg-error')).toHaveCount(0);
  });

  test('в host-режиме токен обновляет хост, а не сам виджет', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', { status: 401, json: { detail: 'token expired' } }, answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await connectHost(page);
    const mintsBefore = server.callsTo('auth.dev-token').length;

    await ask(page, 'Составь письмо');
    await expectAnswer(page);

    // Хост выпустил токен по `sed:auth-token-requested`; виджет сам в СЭД не минтит
    // (иначе он обходил бы модель доступа хост-приложения — 020).
    expect(server.callsTo('auth.dev-token').length).toBe(mintsBefore + 1);
    expect(server.lastCall('intents.process')?.authorization).toMatch(/^Bearer /);
    expect(await navigationCount(page)).toBe(1);
  });
});

test.describe('HITL на проводе', () => {
  test('необратимое действие не уходит до подтверждения step-up', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', {
      json: {
        task_id: 'task-1',
        output: answerDocument('Черновик готов к отправке.'),
        hitl_cards: [{ ...choiceCard(), purpose: 'mcp_tool_approval', risk_score: 0.81 }],
      },
    });
    server.reply('hitl.step-up', {
      json: {
        required: true,
        method: 'idp_acr',
        required_acr: 'silver',
        card_claim: 'hitl_card_id',
        challenge: 'nonce-42',
        authorize_url: null,
        assertion: null,
      },
    });
    server.reply('hitl.respond', {
      json: {
        resolve: {
          card: { ...choiceCard(), status: 'resolved', resolved_action_id: 'formal' },
          replayed: false,
          message: 'ok',
        },
      },
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await ask(page, 'Отправь письмо');
    await page.getByRole('button', { name: 'Официальный' }).click();
    await expect(page.locator('.hitl-step-up-form')).toBeVisible();

    // Ключевая проверка: вызов необратимого действия НЕ отправлен, пока не получен
    // assertion. Если когда-нибудь появится «оптимизация» в обход step-up, упадёт это.
    expect(server.callsTo('hitl.respond')).toHaveLength(0);
    expect(server.callsTo('hitl.step-up')).toHaveLength(1);

    await page.locator('.hitl-step-up-input').fill('idp.jwt.assertion');
    await page.getByRole('button', { name: 'Отправить step-up' }).click();

    const call = server.lastCall('hitl.respond');
    expect(call?.body).toMatchObject({
      action_id: 'formal',
      action_token: 'tok-formal',
      step_up_assertion: 'idp.jwt.assertion',
    });
    // Ключ идемпотентности обязателен: повторный ответ на ту же карточку сервер отвергнет.
    expect(String((call?.body as { idempotency_key?: string }).idempotency_key ?? '')).toContain(
      CARD_ID
    );
  });
});
