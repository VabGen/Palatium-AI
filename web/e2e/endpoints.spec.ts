/**
 * Адреса API и сокета (W9).
 *
 * Топология интеграции — часть контракта с СЭД: либо origin СЭД проксирует
 * `/api` и `/ws` (тогда CORS не нужен), либо задаётся абсолютная база и нужны
 * CORS + WSS. Проверяется два уровня: наблюдаемый (оба пути действительно уходят
 * на один origin страницы) и правило вывода (чистая функция на разных базах —
 * иначе абсолютная база разведёт REST и сокет по разным хостам, и это заметит
 * только стенд СЭД).
 */
import { expect, test, type Page } from '@playwright/test';
import { answerDocument, defaultApi, openWidget, stubSessionSocket } from './fixtures';

/**
 * Вычисляет адреса В СТРАНИЦЕ.
 *
 * Функции адресации — чистые, но вернуть их наружу нельзя: `page.evaluate`
 * сериализует результат и функции теряет. Поэтому таблица «вход → ожидание»
 * считается там же, где живёт модуль. Проверить абсолютную базу через UI не
 * выйдет — она запекается в сборку на `import.meta.env`, — а здесь видно, что
 * REST и сокет выводятся из одного значения.
 *
 * Спецификатор задан переменной намеренно: литерал заставил бы компилятор
 * резолвить путь Vite-модуля как модуль Node.
 */
async function resolveEndpoints(page: Page): Promise<Record<string, string>> {
  return page.evaluate(async () => {
    const specifier = '/src/runtime/endpoints.ts';
    const m = (await import(/* @vite-ignore */ specifier)) as {
      resolveApiBase: (rawBase: string) => string;
      resolveApiUrl: (rawBase: string, input: string) => string;
      resolveSessionSocketUrl: (
        rawBase: string,
        origin: string,
        threadId: string,
        token: string
      ) => string;
    };
    const origin = 'https://edms.example';
    return {
      baseEmpty: m.resolveApiBase(''),
      baseBlank: m.resolveApiBase('  '),
      baseTrailingSlash: m.resolveApiBase('/api/'),
      urlRelative: m.resolveApiUrl('/api', '/intents/process'),
      wsRelative: m.resolveSessionSocketUrl('/api', origin, 'thread-1', 'tok'),
      urlAbsolute: m.resolveApiUrl('https://palatium.example/api', '/intents/process'),
      wsAbsoluteHttps: m.resolveSessionSocketUrl(
        'https://palatium.example/api',
        origin,
        'thread-1',
        'tok'
      ),
      wsAbsoluteHttp: m.resolveSessionSocketUrl(
        'http://palatium.example/api',
        origin,
        'thread-1',
        'tok'
      ),
      wsPrefixed: m.resolveSessionSocketUrl('https://gw.example/palatium/api', origin, 't', 'tok'),
      urlPresigned: m.resolveApiUrl('/api', 'https://minio.example/bucket/item?sig=1'),
      wsEscaped: m.resolveSessionSocketUrl('', origin, 'a/b c', 'tok+/= en'),
    };
  });
}

test.describe('адреса API и сокета', () => {
  test('REST и WS идут на один origin — тот, откуда загружен виджет', async ({ page }) => {
    const server = defaultApi();
    const socketUrls: string[] = [];
    server.reply('intents.process', {
      json: { task_id: 'task-1', output: answerDocument() },
    });
    await stubSessionSocket(page, url => socketUrls.push(url));
    await server.install(page);
    await openWidget(page);

    await page.getByRole('textbox').fill('Составь письмо');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();
    await expect(page.locator('.msg.assistant:not(.pending)')).toHaveCount(1);

    const widgetOrigin = await page.evaluate(() => window.location.origin);
    const call = server.lastCall('intents.process');
    const threadId = (call?.body as { thread_id?: string } | null)?.thread_id ?? '';
    expect(call?.path).toBe('/intents/process');
    expect(threadId).not.toBe('');

    // Сокет открывается на тот же тред, что ушёл в запрос. Если адреса разъедутся,
    // второй origin всплывёт именно здесь.
    expect(socketUrls.length).toBeGreaterThan(0);
    expect(new Set(socketUrls).size, 'адрес сокета стабилен между подключениями').toBe(1);

    const socket = new URL(socketUrls[0]);
    expect(socket.origin.replace(/^ws/, 'http')).toBe(widgetOrigin);
    expect(socket.pathname).toBe(`/ws/sessions/${encodeURIComponent(threadId)}`);
    // Токен — в query: существующий контракт бэкенда Palatium-AI (заголовок браузер
    // в WebSocket не отдаёт), сам токен при этом в storage не попадает.
    expect(socket.searchParams.get('token')).toBe('e2e-token');
  });

  test('правило вывода: относительная база — страница СЭД, абсолютная — её origin', async ({
    page,
  }) => {
    await page.goto('/standalone.html');
    const url = await resolveEndpoints(page);

    // Относительная база — штатная схема: СЭД проксирует оба пути, CORS не нужен.
    expect(url.baseEmpty).toBe('/api');
    expect(url.baseBlank).toBe('/api');
    expect(url.baseTrailingSlash).toBe('/api');
    expect(url.urlRelative).toBe('/api/intents/process');
    expect(url.wsRelative).toBe(`wss://edms.example/ws/sessions/thread-1?token=tok`);

    // Абсолютная база: и REST, и сокет слушают её origin; схема сокета — по схеме
    // базы (`https` → `wss`), иначе браузер заблокирует mixed content на странице СЭД.
    expect(url.urlAbsolute).toBe('https://palatium.example/api/intents/process');
    expect(url.wsAbsoluteHttps).toBe('wss://palatium.example/ws/sessions/thread-1?token=tok');
    expect(url.wsAbsoluteHttp).toBe('ws://palatium.example/ws/sessions/thread-1?token=tok');

    // Префикс развёртывания сохраняется: `…/palatium/api` → `…/palatium/ws/…`.
    expect(url.wsPrefixed).toBe('wss://gw.example/palatium/ws/sessions/t?token=tok');

    // Абсолютный адрес (presigned-URL объектного хранилища) не переписывается.
    expect(url.urlPresigned).toBe('https://minio.example/bucket/item?sig=1');

    // Сегмент треда и токен экранируются: `thread_id` приходит извне, а `/` в пути
    // сокета сменил бы сам эндпоинт.
    expect(url.wsEscaped).toBe('wss://edms.example/ws/sessions/a%2Fb%20c?token=tok%2B%2F%3D%20en');
  });
});
