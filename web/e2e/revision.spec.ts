/**
 * Доработка ответа (W7b): product chat shows the final answer without diff chrome.
 *
 * Server still ships `revision` in the turn payload (SoT), but Kimi-style product
 * UI does not surface "blocks changed / removed" or paint a blue wash over the
 * rewritten answer. Operator/devMode can still opt into chrome in unit tests.
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

test('renders revised answer without product revision chrome', async ({ page }) => {
  const server = defaultApi();
  server.reply('sessions.turns', {
    json: {
      items: [
        { thread_id: THREAD, role: 'user', content: 'Сделай короче', seq: 1 },
        revisedTurn({
          revision_of: 'prev-hash',
          changed_blocks: ['b1'],
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

  await expect(page.getByText('Оплата — по счёту.')).toBeVisible();
  await expect(page.locator('.revision-note')).toHaveCount(0);
  await expect(page.locator('[data-revision="changed"]')).toHaveCount(0);
});

test('legacy revision without indices also stays chrome-free', async ({ page }) => {
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

  await expect(page.locator('.revision-note')).toHaveCount(0);
  await expect(page.locator('[data-revision="changed"]')).toHaveCount(0);
});
