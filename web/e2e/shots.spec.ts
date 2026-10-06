/**
 * Визуальная сверка палитры — по запросу, НЕ гейт.
 *
 * Светлая тема задана расчётно (правило 6 плана): контраст проверен программно
 * (`a11y.spec.ts` — axe в обеих темах), но «как это выглядит» автотест не решает.
 * Этот файл снимает кадры в обеих темах, чтобы человек сверил результат после
 * правки токенов; сравнения с базлайном нет, поэтому в обычном прогоне он пропускается.
 *
 * Запуск: `npm run test:shots` (кадры падают в `web/.shots/`).
 */
import { test } from '@playwright/test';
import {
  answerDocument,
  defaultApi,
  openWidget,
  stepUpChallenge,
  stubSessionSocket,
  toolCard,
} from './fixtures';

const SHOTS = '.shots';
const ONLY_ON_DEMAND = 'визуальная сверка запускается по запросу: npm run test:shots';

test.beforeEach(() => {
  test.skip(!process.env.SHOTS, ONLY_ON_DEMAND);
});

test('тёмная тема: пустой диалог', async ({ page }) => {
  const server = defaultApi();
  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);
  await page.screenshot({ path: `${SHOTS}/01-dark-empty.png` });
});

test('светлая тема: пустой диалог', async ({ page }) => {
  const server = defaultApi();
  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);
  await page.getByRole('button', { name: 'Тема: светлая' }).click();
  await page.screenshot({ path: `${SHOTS}/02-light-empty.png` });
});

test('светлая тема: карточка инструмента и панель памяти', async ({ page }) => {
  const server = defaultApi();
  server.reply('intents.process', {
    json: {
      task_id: 'task-1',
      output: answerDocument(),
      hitl_cards: [toolCard()],
    },
  });
  server.reply('hitl.step-up', { json: stepUpChallenge() });
  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);
  await page.getByRole('button', { name: 'Тема: светлая' }).click();
  await page.getByRole('textbox').fill('Отправь письмо контрагенту');
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
  await page.locator('.hitl-card').waitFor();
  await page.getByRole('button', { name: 'Память' }).click();
  await page.screenshot({ path: `${SHOTS}/03-light-hitl.png` });

  // Самый плотный по кнопкам кадр: шаг подтверждения необратимого действия.
  await page.locator('.hitl-card').getByRole('button', { name: 'Отправить', exact: true }).click();
  await page.locator('.hitl-step-up-form').waitFor();
  await page.screenshot({ path: `${SHOTS}/04-light-step-up.png` });
});

test('светлая тема: свёрнутый лончер', async ({ page }) => {
  const server = defaultApi();
  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);
  await page.getByRole('button', { name: 'Тема: светлая' }).click();
  await page.getByRole('button', { name: 'Свернуть: close()' }).click();
  await page.screenshot({ path: `${SHOTS}/05-light-collapsed.png` });
});
