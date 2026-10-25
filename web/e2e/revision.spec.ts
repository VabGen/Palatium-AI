/**
 * Доработка ответа (W7b): живой diff в ленте.
 *
 * Проверяется то, что видит человек и что нельзя увидеть в jsdom: заметка о
 * ревизии, полоса у изменённого блока в реальной вёрстке и честный отказ от
 * подсветки, когда сервер не прислал позиции (payload до UI-волны).
 */
import { expect, test } from '@playwright/test';

import { answerDocument, defaultApi, openWidget, stubSessionSocket } from './fixtures';

const THREAD = 'thread-e2e';

/** Сохранённый ход с документом и diff'ом — ровно то, что пишет сервер в payload. */
function revisedTurn(revision: Record<string, unknown>) {
  const document = answerDocument('Срок — 10 рабочих дней.');
  document.blocks.push({ type: 'paragraph', text: 'Оплата — по счёту.' });
  return {
    thread_id: THREAD,
    role: 'assistant',
    content: 'Срок — 10 рабочих дней.\nОплата — по счёту.',
    seq: 2,
    payload: {
      schema: 'assistant_turn_v1',
      document,
      hitl_cards: [],
      revision,
    },
  };
}

test('помечает изменённый блок и называет счётчики diff-а', async ({ page }) => {
  const server = defaultApi();
  server.reply('sessions.turns', {
    json: {
      items: [
        { thread_id: THREAD, role: 'user', content: 'Сделай короче', seq: 1 },
        revisedTurn({
          revision_of: 'prev-hash',
          changed_blocks: ['b1'],
          // `answerDocument` уже содержит два блока — абзац и kv; добавленный абзац третий.
          changed_block_indices: [2],
          removed_blocks: ['gone'],
          unchanged_blocks: 2,
        }),
      ],
    },
  });
  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);

  const note = page.locator('.revision-note');
  await expect(note).toContainText('Ответ доработан');
  await expect(note).toContainText('изменено блоков: 1');
  await expect(note).toContainText('удалено: 1');

  // Ровно тот блок, на который указал сервер, а не «все подряд».
  const marked = page.locator('[data-revision="changed"]');
  await expect(marked).toHaveCount(1);
  await expect(marked).toContainText('Оплата — по счёту.');
  // Факт изменения озвучен, а не только нарисован полосой.
  await expect(marked).toContainText('Изменённый блок');
});

test('без индексов показывает счётчики, но не подсвечивает блоки', async ({ page }) => {
  const server = defaultApi();
  server.reply('sessions.turns', {
    json: {
      items: [
        revisedTurn({
          revision_of: 'prev-hash',
          changed_blocks: ['b1'],
          removed_blocks: [],
          unchanged_blocks: 1,
        }),
      ],
    },
  });
  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);

  await expect(page.locator('.revision-note')).toContainText('изменено блоков: 1');
  await expect(page.locator('[data-revision="changed"]')).toHaveCount(0);
});
