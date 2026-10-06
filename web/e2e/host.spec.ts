/**
 * Контракт хост ↔ виджет (W8) — то, что не сводится к кадрам UI.
 *
 * Локаль и тема задаются ХОСТОМ (атрибуты `lang` / `data-theme`), поэтому
 * переключение обязано проходить вживую: без перезагрузки страницы СЭД (план §4.1)
 * и без потери состояния диалога. Матрица состояний проверяет, что виджет ВЫГЛЯДИТ
 * правильно, здесь — что он ПЕРЕКЛЮЧАЕТСЯ правильно.
 */
import { expect, test, type Page } from '@playwright/test';
import {
  announcedThreads,
  ASSISTANT,
  answerDocument,
  defaultApi,
  dialogTurn,
  formatterResult,
  hostContextForTest,
  navigationCount,
  openWidget,
  sendHostContext,
  stubSessionSocket,
  toolCard,
  trackThreadEvents,
  visibleStrings,
} from './fixtures';
import type { MockServer } from './mock-server';

/** Отправить сообщение так, как это делает человек: ввод + клик отправки. */
async function ask(page: Page, text: string): Promise<void> {
  await page.getByRole('textbox').fill(text);
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
}

/**
 * Пути, по которым виджет просил историю диалога.
 *
 * Порядок фиксации в моке — порядок ПРИХОДА запросов, а не порядок их отправки:
 * запрос автономного треда может прийти позже, чем запрос тредa host'а. Поэтому
 * проверяем вхождение нужного пути, а не «последний вызов».
 */
function historyPaths(server: MockServer): string[] {
  return server.callsTo('sessions.turns').map(call => call.path);
}

test.describe('атрибуты хоста', () => {
  test('смена lang переключает интерфейс без перезагрузки и без потери диалога', async ({
    page,
  }) => {
    const server = defaultApi();
    server.reply('intents.process', {
      json: { task_id: 'task-1', output: answerDocument('Черновик письма готов.') },
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await expect(page.getByRole('button', { name: 'Новый диалог' })).toBeVisible();
    await page.getByRole('textbox').fill('Составь письмо');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();
    await expect(page.locator('.msg.assistant:not(.pending)')).toHaveCount(1);
    const turnsBefore = server.callsTo('sessions.turns').length;

    // Так это делает СЭД: атрибут на элементе, никаких наших API.
    await page
      .locator('palatium-assistant')
      .evaluate(element => element.setAttribute('lang', 'en'));

    await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Новый диалог' })).toHaveCount(0);
    await expect(page.getByRole('textbox')).toHaveAttribute('placeholder', 'Message Palatium…');
    // Язык фрагмента меняется вместе с интерфейсом: иначе скринридер читает
    // английский текст русским голосом.
    await expect(page.locator('palatium-assistant')).toHaveAttribute('lang', 'en');

    // Диалог на месте: смена локали — не новый тред и не перезагрузка страницы.
    await expect(page.locator('.msg.user')).toHaveCount(1);
    await expect(page.locator('.msg.assistant:not(.pending)')).toHaveCount(1);
    expect(server.callsTo('sessions.turns')).toHaveLength(turnsBefore);
    expect(await navigationCount(page)).toBe(1);
  });
});

test.describe('локаль контекста', () => {
  // Язык браузера намеренно чужой: внутри СЭД он не должен подменять язык host'а.
  test.use({ locale: 'en-US' });

  test("неизвестная локализация host'а не откатывается к языку браузера", async ({ page }) => {
    const server = defaultApi();
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // Стенд (как и любой host) пиннит язык атрибутом; снимаем его, чтобы локаль
    // браузера стала наблюдаемой — иначе `lang` перекрывает контекст.
    await page.locator(ASSISTANT).evaluate(element => element.removeAttribute('lang'));
    await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible();

    // `GE` объявлена в СЭД, но ресурсов для неё нет: их `i18n.js` рендерит RU
    // (`fallbackLng`). Значит и виджет обязан быть русским, хотя браузер — en-US:
    // иначе внутри русской страницы появится англоязычная панель.
    await sendHostContext(page, hostContextForTest({ localization: 'GE' }));
    await expect(page.getByRole('button', { name: 'Новый диалог' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'New chat' })).toHaveCount(0);

    // Явный `lang` на элементе остаётся рычагом host'а, если ресурсы появятся.
    await page.locator(ASSISTANT).evaluate(element => element.setAttribute('lang', 'en'));
    await expect(page.getByRole('button', { name: 'New chat' })).toBeVisible();
  });

  test("форматы даты и числа следуют языку host'а, а не языку браузера", async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process', {
      json: formatterResult({ output: null, hitl_cards: [toolCard()] }),
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // Стенд (как и любой host) пиннит язык атрибутом; снимаем его, чтобы локаль
    // браузера стала наблюдаемой, и отдаём контекст с русской локализацией СЭД.
    await page.locator(ASSISTANT).evaluate(element => element.removeAttribute('lang'));
    await sendHostContext(page, hostContextForTest({ localization: 'RU' }));
    await expect(page.getByRole('button', { name: 'Новый диалог' })).toBeVisible();

    await page.getByRole('textbox').fill('Отправь письмо через EDMS');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();

    const expiry = page.locator('.hitl-meta span').filter({ hasText: 'Истекает' });
    const risk = page.locator('.hitl-meta span').filter({ hasText: 'Риск' });
    await expect(expiry).toHaveCount(1);

    // Браузер здесь en-US: 12-часовой формат и точка в дробной части были бы
    // форматом БРАУЗЕРА внутри русской страницы. Формат задаёт язык интерфейса.
    await expect(expiry).toHaveText(/^Истекает \d{2}:\d{2}:\d{2}$/);
    await expect(risk).toHaveText(/^Риск 0,81$/);

    // Тот же рычаг host'а в обратную сторону: язык сменился — сменился и формат.
    await page.locator(ASSISTANT).evaluate(element => element.setAttribute('lang', 'en'));
    await expect(page.locator('.hitl-meta span').filter({ hasText: 'Expires' })).toHaveText(
      /^Expires \d{1,2}:\d{2}:\d{2} (AM|PM)$/
    );
    await expect(page.locator('.hitl-meta span').filter({ hasText: 'Risk' })).toHaveText(
      /^Risk 0\.81$/
    );
  });
});

test.describe('персонализация', () => {
  test("обращение по имени берётся из контекста host'а, а не угадывается", async ({ page }) => {
    const server = defaultApi();
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // Автономно host'а нет — обращаться не по чему; приветствие не выдумывается.
    await expect(page.locator('.empty-greeting')).toHaveCount(0);

    // Без `firstName` полное имя показываем КАК ЕСТЬ: в СЭД это «Фамилия Имя»,
    // и разбор по позиции дал бы обращение по фамилии.
    await sendHostContext(page, hostContextForTest({ firstName: undefined }));
    await expect(page.locator('.empty-greeting')).toHaveText('Здравствуйте, Петров Иван');

    // `firstName` — явная форма обращения от host'а: приоритет у неё.
    await sendHostContext(page, hostContextForTest({ firstName: 'Иван' }));
    await expect(page.locator('.empty-greeting')).toHaveText('Здравствуйте, Иван');

    // Приветствие — часть переводимого интерфейса, а не склейка в разметке.
    await page.locator(ASSISTANT).evaluate(element => element.setAttribute('lang', 'en'));
    await expect(page.locator('.empty-greeting')).toHaveText('Hello, Иван');
    // Подстановка сохраняет имя как есть: это имя человека, а не число с разрядами.
    expect(await visibleStrings(page)).not.toContain('Hello, {name}');
  });
});

test.describe('граница доверия контекста', () => {
  test('контекст с чужим tenant не принимается, согласованный — принимается', async ({ page }) => {
    const server = defaultApi();
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // Host молчит → автономный режим (окно 500 мс).
    await expect(page.locator(ASSISTANT).getByText('автономно', { exact: true })).toBeVisible();

    // Токен от другой организации при `scope.tenantId` этой: сервер обслуживал бы
    // tenant из токена, а UI показывал бы данные другого — тихая путаница.
    await sendHostContext(
      page,
      hostContextForTest({ tenantId: 'org-e2e', tokenOrgId: 'org-other' })
    );
    await expect(page.locator(ASSISTANT).getByText('автономно', { exact: true })).toBeVisible();

    // Тот же токен повторно: отказ не «залипает» и не спамит сообщениями.
    await sendHostContext(
      page,
      hostContextForTest({ tenantId: 'org-e2e', tokenOrgId: 'org-other' })
    );
    await expect(page.locator(ASSISTANT).getByText('автономно', { exact: true })).toBeVisible();

    // Согласованный контекст принимается тем же слушателем — отказ не «залипает».
    await sendHostContext(page, hostContextForTest({ tenantId: 'org-e2e' }));
    await expect(page.locator(ASSISTANT).getByText('автономно', { exact: true })).toHaveCount(0);
  });

  test('токен без tenant-claim принимается: сверять нечего', async ({ page }) => {
    const server = defaultApi();
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // dev-токен стенда (`e2e-token`) не JWT: это неизвестность, а не расхождение.
    await sendHostContext(page, hostContextForTest({ tokenOrgId: null }));
    await expect(page.locator(ASSISTANT).getByText('автономно', { exact: true })).toHaveCount(0);

    // Контекст принят (host-режим), а не «висит в ожидании»: спустя окно рукопожатия
    // автономного бейджа всё ещё нет.
    await page.waitForTimeout(700);
    await expect(page.locator(ASSISTANT).getByText('автономно', { exact: true })).toHaveCount(0);
  });
});

test.describe('непрерывность диалога', () => {
  test('виджет объявляет тред, который создал сам, — host его сохраняет', async ({ page }) => {
    const server = defaultApi();
    server.reply('sessions.turns', { json: { items: [] } });
    await trackThreadEvents(page);
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // Тред объявляется и в автономном режиме: сохранять его — работа host'а, и без
    // объявления он не узнает id, пока пользователь не отправит первое сообщение.
    await sendHostContext(page, hostContextForTest());
    await expect(page.locator(ASSISTANT).getByText('автономно', { exact: true })).toHaveCount(0);

    const announced = await announcedThreads(page);
    expect(announced).toHaveLength(1);
    // Хост получает ровно тот тред, которым виджет ходит в API. Проверяем вхождение,
    // а не «последний вызов»: порядок фиксации в моке — порядок прихода запросов, и
    // запрос автономного треда может прийти позже, чем запрос тредa host'а.
    expect(historyPaths(server)).toContain(`/sessions/${announced[0]}/turns`);

    // «Новый диалог» — новый тред, и host узнаёт о нём тем же событием.
    await page.getByRole('button', { name: 'Новый диалог' }).click();
    await expect
      .poll(async () => (await announcedThreads(page)).length, {
        message: 'объявление нового треда',
      })
      .toBe(2);
    const afterNewChat = await announcedThreads(page);
    expect(afterNewChat[1]).not.toBe(afterNewChat[0]);
    expect(historyPaths(server)).toContain(`/sessions/${afterNewChat[1]}/turns`);
    // Старый тред host'у больше не объявляется: «новый диалог» — одно событие.
    expect(afterNewChat.filter(thread => thread === afterNewChat[0])).toHaveLength(1);
  });

  test("тред из контекста продолжается после перезагрузки, и эха host'у не летит", async ({
    page,
  }) => {
    const server = defaultApi();
    const restored = '11111111-2222-4333-8444-555555555555';
    server.reply('sessions.turns', {
      json: { items: [dialogTurn('user', 'Вопрос до перезагрузки', 1)] },
    });
    server.reply('intents.process', { json: { task_id: 'task-1', output: answerDocument() } });
    await trackThreadEvents(page);
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // Так это делает СЭД: id взят из прошлого запуска и лежит у host'а.
    await sendHostContext(page, hostContextForTest({ threadId: restored }));

    // История запрашивается ПО ЭТОМУ треду, а не по свежесгенерированному:
    // иначе после перезагрузки страницы диалог начинался бы с нуля.
    await expect
      .poll(() => historyPaths(server).includes(`/sessions/${restored}/turns`), {
        message: "история должна грузиться по треду host'а",
      })
      .toBe(true);
    await expect(page.locator('.msg.user')).toContainText('Вопрос до перезагрузки');

    // Настоящая проверка непрерывности — не путь запроса истории, а запрос,
    // который виджет отправляет ДАЛЬШЕ: он должен уйти в тред host'а, иначе
    // продолжение диалога создало бы второй, параллельный тред.
    await ask(page, 'Продолжаем');
    expect((server.lastCall('intents.process')?.body as { thread_id: string }).thread_id).toBe(
      restored
    );

    // Эха нет: id прислал host, значит он его уже знает. Объявить виджет вправе
    // только свой тред (и то лишь если не успел получить контекст) — но не этот.
    await page.waitForTimeout(700);
    expect(await announcedThreads(page)).not.toContain(restored);

    // А новый диалог host'а уже касается — он получает новый id тем же событием.
    await page.getByRole('button', { name: 'Новый диалог' }).click();
    await expect
      .poll(async () => (await announcedThreads(page)).length, {
        message: 'объявление нового треда',
      })
      .toBeGreaterThan(0);
    expect(await announcedThreads(page)).not.toContain(restored);
  });
});
