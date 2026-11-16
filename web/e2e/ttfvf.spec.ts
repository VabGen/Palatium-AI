/**
 * TTFVF-гейт (W1-клиент): «пользователь видит отклик не позже 300 мс».
 *
 * Почему это E2E, а не юнит-тест: величина включает commit React'а и отрисовку
 * кадра браузером. Ни jsdom, ни расчёт «сколько должен стоить рендер» этого не
 * показывают — измеряется только реальный Chromium.
 *
 * Сценарий намеренно медленный на СТОРОНЕ СЕРВЕРА (задержка ответа): так видно
 * главное обещание W1 — заглушка turn'а появляется до контента, а не вместе с
 * ним. Метрика пишется в `performance` таймлайн (`palatium:ttfvf`), оттуда её и
 * читает гейт; в сеть ничего не отправляется (020 — данные остаются у хоста).
 */
import { expect, test } from '@playwright/test';
import { TTFVF_BUDGET_MS, TTFVF_MEASURE } from '../src/lib/firstVisual';
import {
  answerDocument,
  defaultApi,
  formatterResult,
  openWidget,
  stubSessionSocket,
} from './fixtures';

test.describe('TTFVF', () => {
  test("заглушка turn'а отрисована в пределах бюджета и до контента", async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process.stream', {
      // Задержка сервера — окно, в котором видна заглушка. Без неё «до контента»
      // неотличимо от «вместе с контентом».
      delayMs: 900,
      json: formatterResult({ output: answerDocument() }),
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.locator('.composer-textarea').fill('Составь письмо');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();

    // Первый видимый кадр — орб ожидания (W2: единственная заглушка turn'а).
    await expect(page.locator('.msg.is-waiting .thinking-indicator')).toBeVisible();
    // Контента ещё нет: ответ придёт через ~900 мс.
    await expect(page.locator('.msg.assistant .block-paragraph')).toHaveCount(0);

    await page.waitForFunction(
      name => performance.getEntriesByName(name).length > 0,
      TTFVF_MEASURE
    );

    const entries = await page.evaluate(
      name => performance.getEntriesByName(name).map(entry => ({ duration: entry.duration })),
      TTFVF_MEASURE
    );

    // Одно измерение на turn, а не на кадр.
    expect(entries).toHaveLength(1);
    expect(entries[0]?.duration ?? Number.POSITIVE_INFINITY).toBeLessThanOrEqual(TTFVF_BUDGET_MS);
  });

  test("regenerate измеряется отдельным turn'ом", async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process.stream', { json: formatterResult({ output: answerDocument() }) });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.locator('.composer-textarea').fill('Составь письмо');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();
    await expect(page.locator('.msg.assistant .block-paragraph')).toBeVisible();

    const measureCount = () =>
      page.evaluate(name => performance.getEntriesByName(name).length, TTFVF_MEASURE);

    // Отправка — один turn, значит и одно измерение.
    expect(await measureCount()).toBe(1);

    // Ответ уже пришёл, поэтому очередь мока повторяет тот же успешный ответ.
    await page.getByRole('button', { name: 'Сформировать ответ заново' }).click();

    await expect.poll(measureCount).toBe(2);
  });
});
