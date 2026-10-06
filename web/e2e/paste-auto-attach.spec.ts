/**
 * Paste auto-attach (Wave 1): длинная вставка → chip → attachments API.
 *
 * Пороги зеркалят `AUTO_ATTACH_CHARS` / `INTENT_TEXT_LIMIT` — Playwright не
 * импортирует `src/` с `import.meta.env` (Vite).
 */
import { expect, test } from '@playwright/test';
import { ru } from '../src/i18n/messages';
import {
  ATTACHMENT_ID,
  answerDocument,
  defaultApi,
  openWidget,
  pasteIntoComposer,
  stubPastedTextUpload,
  stubSessionSocket,
} from './fixtures';
import type { Reply } from './mock-server';

/** SoT: `web/src/lib/attachments.ts` */
const AUTO_ATTACH_CHARS = 10_000;
/** SoT: `web/src/api/client.ts` (`MAX_INTENT_TEXT`) */
const INTENT_TEXT_LIMIT = 32_000;

function answer(): Reply {
  return { json: { task_id: 'task-paste', output: answerDocument() } };
}

async function expectAnswer(page: import('@playwright/test').Page): Promise<void> {
  await expect(page.locator('.msg.assistant:not(.pending)')).toHaveCount(1);
}

test.describe('paste auto-attach', () => {
  test('короткая вставка остаётся в поле — attachments.init не вызывается', async ({ page }) => {
    const short = 'я'.repeat(AUTO_ATTACH_CHARS);
    const server = defaultApi();
    server.reply('intents.process', answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await pasteIntoComposer(page, short);

    await expect(page.getByRole('textbox')).toHaveValue(short);
    await expect(page.locator('.attachment-chip')).toHaveCount(0);
    expect(server.callsTo('attachments.init')).toHaveLength(0);
  });

  test('вставка > AUTO_ATTACH становится text/plain chip и уходит как attachment_ids', async ({
    page,
  }) => {
    const longText = 'я'.repeat(AUTO_ATTACH_CHARS + 1);
    const server = defaultApi();
    stubPastedTextUpload(server, longText);
    server.reply('attachments.delete', { status: 204, json: {} });
    server.reply('intents.process', answer());
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await pasteIntoComposer(page, longText);

    await expect(page.locator('.attachment-chip.is-paste.is-ready')).toBeVisible();
    await expect(page.getByRole('textbox')).toHaveValue('');
    await expect(page.getByText(ru['composer.asDocument'])).toBeVisible();

    await page.getByRole('button', { name: 'Отправить сообщение' }).click();
    await expectAnswer(page);

    const init = server.lastCall('attachments.init');
    expect(init?.body).toMatchObject({ mime_type: 'text/plain', mode: 'attach' });
    expect(String((init?.body as { filename?: string }).filename ?? '')).toMatch(
      /^pasted-text_\d{4}-\d{2}-\d{2}\.txt$/
    );
    expect(server.callsTo('attachments.complete')).toHaveLength(1);
    expect(server.lastCall('intents.process')?.body).toMatchObject({
      attachment_ids: [ATTACHMENT_ID],
      text: ru['composer.pastedDefaultPrompt'],
    });
    const intentText = String(
      (server.lastCall('intents.process')?.body as { text?: string }).text ?? ''
    );
    expect(intentText).not.toContain(longText.slice(0, 40));
  });

  test('«Показать в поле ввода» возвращает текст ≤ INTENT_TEXT_LIMIT и удаляет chip', async ({
    page,
  }) => {
    // Между AUTO_ATTACH и INTENT_TEXT_LIMIT — chip создаётся, но restore в поле легален.
    const restorable = 'б'.repeat(AUTO_ATTACH_CHARS + 50);
    expect(restorable.length).toBeLessThanOrEqual(INTENT_TEXT_LIMIT);

    const server = defaultApi();
    const filename = stubPastedTextUpload(server, restorable);
    server.reply('attachments.delete', { status: 204, json: {} });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await pasteIntoComposer(page, restorable);
    await expect(page.locator('.attachment-chip.is-paste.is-ready')).toBeVisible();

    // Paste chip is text, not a table — analyze action must not appear.
    await expect(page.getByRole('button', { name: ru['attach.analyze'] })).toHaveCount(0);

    await page.getByRole('button', { name: ru['composer.showInField'] }).click();

    await expect(page.locator('.attachment-chip')).toHaveCount(0);
    await expect(page.getByRole('textbox')).toHaveValue(restorable);
    expect(server.callsTo('attachments.delete')).toHaveLength(1);
    expect(server.lastCall('attachments.delete')?.path).toContain(ATTACHMENT_ID);
    expect(filename).toMatch(/^pasted-text_/);
    expect(server.callsTo('intents.process')).toHaveLength(0);
  });

  test('Удалить chip шлёт DELETE и не шлёт intent', async ({ page }) => {
    const longText = 'в'.repeat(AUTO_ATTACH_CHARS + 1);
    const server = defaultApi();
    const filename = stubPastedTextUpload(server, longText);
    server.reply('attachments.delete', { status: 204, json: {} });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await pasteIntoComposer(page, longText);
    await expect(page.locator('.attachment-chip.is-paste.is-ready')).toBeVisible();

    await page
      .getByRole('button', { name: ru['composer.removeAttachment'].replace('{name}', filename) })
      .click();

    await expect(page.locator('.attachment-chip')).toHaveCount(0);
    await expect(page.getByRole('textbox')).toHaveValue('');
    expect(server.callsTo('attachments.delete')).toHaveLength(1);
    expect(server.callsTo('intents.process')).toHaveLength(0);
  });

  test('«Показать в поле» при тексте > INTENT_TEXT_LIMIT оставляет chip', async ({ page }) => {
    const tooLongForField = 'г'.repeat(INTENT_TEXT_LIMIT + 1);
    const server = defaultApi();
    stubPastedTextUpload(server, tooLongForField);
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await pasteIntoComposer(page, tooLongForField);
    await expect(page.locator('.attachment-chip.is-paste.is-ready')).toBeVisible();

    await page.getByRole('button', { name: ru['composer.showInField'] }).click();

    // Toast + chip остаётся: поле не может вместить 32k+.
    await expect(page.locator('.attachment-chip.is-paste')).toBeVisible();
    await expect(page.getByRole('textbox')).toHaveValue('');
    expect(server.callsTo('attachments.delete')).toHaveLength(0);
  });
});
