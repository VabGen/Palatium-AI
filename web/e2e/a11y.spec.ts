/**
 * Доступность и клавиатура (W8).
 *
 * Гейт стоит на `standalone.html` — на том же стенде, что и остальные E2E, — а не
 * на странице-хосте: страницу СЭД мы не контролируем, а виджет обязан быть
 * доступным независимо от неё.
 *
 * Проверки делятся на два класса:
 *  1. axe (WCAG A/AA) в обеих темах — включая Shadow DOM, который axe обходит
 *     сам, потому что shadow root открыт;
 *  2. клавиатура и фокус: попадание в Shadow DOM, порядок обхода, видимый
 *     индикатор фокуса, активация карточки с клавиатуры, reduced-motion.
 */
import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';
import { ru } from '../src/i18n/messages';
import type { ContentDocument } from '../src/types/contentDocument';
import {
  answerDocument,
  defaultApi,
  formatterResult,
  openWidget,
  stepUpChallenge,
  stubSessionSocket,
  toolCard,
} from './fixtures';

/** SSE-тело кадрами: нужен ровно тот порядок, в котором их шлёт сервер. */
function sse(frames: Array<{ event: string; data: unknown }>): string {
  return frames
    .map(frame => `event: ${frame.event}\ndata: ${JSON.stringify(frame.data)}\n\n`)
    .join('');
}

/** Снимок сфокусированного элемента внутри Shadow DOM виджета. */
type FocusSnapshot = {
  tag: string;
  className: string;
  label: string;
  outlineStyle: string;
  outlineWidth: string;
};

async function activeInWidget(page: Page): Promise<FocusSnapshot | null> {
  return page.evaluate(() => {
    const root = document.querySelector('palatium-assistant')?.shadowRoot;
    const active = root?.activeElement;
    if (!active) return null;
    const style = getComputedStyle(active);
    return {
      tag: active.tagName.toLowerCase(),
      className: typeof active.className === 'string' ? active.className : '',
      label: active.getAttribute('aria-label') ?? active.textContent?.trim().slice(0, 30) ?? '',
      outlineStyle: style.outlineStyle,
      outlineWidth: style.outlineWidth,
    };
  });
}

/**
 * Обход с клавиатуры, начиная со страницы-хоста.
 *
 * Начинаем не с «первого элемента страницы»: так проверяется именно то, что
 * последовательность не обрывается на границе Shadow DOM.
 */
async function tabInto(page: Page, limit: number): Promise<FocusSnapshot[]> {
  const visited: FocusSnapshot[] = [];
  for (let press = 0; press < 40 && visited.length < limit; press++) {
    await page.keyboard.press('Tab');
    const active = await activeInWidget(page);
    if (active) visited.push(active);
  }
  return visited;
}

/**
 * Один ход до готового документа: задерживающий ответ не нужен, проверяется
 * итоговая отрисовка блоков (там и живёт анимированная иконка).
 */
async function runStream(page: Page, output: ContentDocument): Promise<void> {
  const server = defaultApi();
  server.reply('intents.process.stream', { json: { task_id: 'task-1', output } });
  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);
  await page.locator('.composer-textarea').fill('Составь письмо');
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
}

/**
 * Документ с callout, чей явный `icon` заведомо попадает в Lottie-таблицу.
 * `icon` задан явно: проверяется рендер иконки, а не деривация из тона.
 */
function documentWithAnimatedCallout(icon: 'success' | 'danger'): ContentDocument {
  const document = answerDocument();
  document.blocks.push({ type: 'callout', tone: 'success', icon, body: 'Проверка статуса.' });
  return document;
}

async function scan(page: Page): Promise<void> {
  // Тег `palatium-assistant` добавлен в исключения быть не может: виджет — часть
  // проверяемой поверхности. Сканируем весь документ, Shadow DOM axe обходит сам.
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze();

  const summary = results.violations.map(
    violation =>
      `${violation.id} (${violation.impact ?? 'n/a'}): ${violation.nodes
        .map(node => node.target.join(' '))
        .join(' | ')}`
  );
  expect(summary, 'нарушения WCAG в виджете').toEqual([]);
}

test.describe('axe (WCAG A/AA)', () => {
  test('светлая тема выбирается атрибутом и проходит контраст', async ({ page }) => {
    const server = defaultApi();
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.getByRole('button', { name: 'Тема: светлая' }).click();
    await expect(page.locator('palatium-assistant')).toHaveAttribute('data-theme', 'light');
    await scan(page);
  });

  test('карточка HITL и панель памяти доступны с клавиатуры', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process.stream', {
      json: {
        task_id: 'task-1',
        output: answerDocument(),
        hitl_cards: [toolCard()],
      },
    });
    // Необратимая операция: сервер требует step-up, значит `/respond` до
    // подтверждения уходить не должен — это и проверяет клавиатурный тест.
    server.reply('hitl.step-up', { json: stepUpChallenge() });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.locator('.composer-textarea').fill('Отправь письмо');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();
    await page.getByRole('button', { name: 'Память' }).click();
    await expect(page.locator('.hitl-card')).toBeVisible();

    // Панель памяти и карточка живут в одном дереве — нарушений быть не должно.
    await scan(page);

    // Карточка активируется клавиатурой: фокус на вариант + Enter.
    const option = page
      .locator('.hitl-card')
      .getByRole('button', { name: 'Отправить', exact: true });
    await option.focus();
    await expect(option).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('.hitl-step-up-form')).toBeVisible();
    await scan(page);

    // Enter открыл шаг подтверждения, а не выполнил действие: необратимая
    // операция уходит на сервер только после ввода assertion (020).
    expect(server.callsTo('hitl.respond')).toHaveLength(0);
  });
});

test.describe('клавиатура и фокус внутри Shadow DOM', () => {
  test('обход доходит до каждого контрола и оставляет видимый фокус', async ({ page }) => {
    const server = defaultApi();
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // `palatium:ready` — это апгрейд элемента, а не конец загрузки: пустое
    // состояние с подсказками появляется только после гидратации истории
    // (`sessions/turns`). Без ожидания обход стартует раньше вставки этих
    // кнопок и проскакивает их — тест падал на порядке, а не на доступности.
    await expect(page.locator('.suggestion')).toHaveCount(3);

    // Стартовая точка задаётся явно. Браузер запоминает «место, где остановился
    // Tab» на момент загрузки, а виджет к тому времени ещё дорисовывается, —
    // без якоря обход начинается не с первого контроля. Якорь на последнем
    // контроле страницы-хоста заодно проверяет главное: последовательность не
    // обрывается на границе Shadow DOM, а продолжается внутри виджета.
    await page.locator('#btn-expand').focus();
    const visited = await tabInto(page, 6);

    // Composer v2: шапка → pill-starters → один `+` (attach/project/memory в меню).
    // `.send-btn` нет: пустой ввод → disabled. Скрепка снаружи убрана.
    expect(visited.map(item => `${item.tag}.${item.className.split(' ')[0]}`)).toEqual([
      'button.toolbar-btn',
      'button.toolbar-btn',
      'button.suggestion',
      'button.suggestion',
      'button.suggestion',
      'button.tools-btn',
    ]);

    // Индикатор фокуса обязателен для каждого шага, а не только «в среднем»:
    // без него пользователь не знает, где находится.
    for (const item of visited) {
      expect(item.outlineStyle, `${item.tag}.${item.className}`).toBe('solid');
      expect(item.outlineWidth, `${item.tag}.${item.className}`).toBe('2px');
    }
  });

  test('заполненный ввод делает отправку достижимой с клавиатуры', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process.stream', {
      json: { task_id: 'task-1', output: answerDocument() },
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.locator('.composer-textarea').fill('Составь письмо');
    await expect(page.getByRole('button', { name: 'Отправить сообщение' })).toBeEnabled();

    // Между textarea и send нет ничего фокусируемого — один Tab.
    const next: FocusSnapshot[] = [];
    for (let press = 0; press < 4 && next.length === 0; press++) {
      await page.keyboard.press('Tab');
      const active = await activeInWidget(page);
      if (active) next.push(active);
    }
    expect(next[0]?.className).toContain('send-btn');
  });
});

test.describe('Artifacts pane', () => {
  test('достойный документ открывается в панели; Esc закрывает', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process.stream', {
      json: formatterResult({ output: answerDocument() }),
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.locator('.composer-textarea').fill('Составь план');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();

    const pane = page.getByRole('complementary', { name: ru['artifact.paneLabel'] });
    await expect(pane).toBeVisible();
    await expect(page.locator('.msg.assistant .artifact-anchor')).toBeVisible();
    await expect(pane.locator('.doc')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(pane).toHaveCount(0);

    await page.locator('.artifact-anchor').click();
    await expect(page.getByRole('complementary', { name: ru['artifact.paneLabel'] })).toBeVisible();
    await expect(
      page.getByRole('button', { name: ru['artifact.close'] })
    ).toBeFocused();
  });
});

test.describe('канал озвучивания стрима (W2)', () => {
  /**
   * Гейт на разметку и на главный инвариант: лента НЕ объявляет себя сама, а
   * прогресс идёт отдельным живым регионом. Поведение VoiceOver/NVDA этим не
   * проверяется — для него в `web/e2e/` лежит ручной чек-лист.
   */
  test('лента — log без автообъявлений, финал приходит отдельным регионом', async ({ page }) => {
    const server = defaultApi();
    server.reply('intents.process.stream', {
      text: sse([
        { event: 'document_title', data: { title: 'Итоги' } },
        {
          event: 'block_delta',
          data: { index: 0, block: { type: 'paragraph', text: 'Первый закрытый блок.' } },
        },
        {
          event: 'block_delta',
          data: {
            index: 1,
            block: { type: 'table', columns: ['Поле', 'Значение'], rows: [['a', '1']] },
          },
        },
        {
          event: 'result',
          data: { result: formatterResult({ output: { ...answerDocument(), title: 'Итоги' } }) },
        },
        { event: 'done', data: {} },
      ]),
      contentType: 'text/event-stream',
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    // Лента — log ровно с выключенными объявлениями: иначе каждый block_delta
    // превращался бы в лавину перечитываний всего ответа.
    const log = page.locator('.transcript');
    await expect(log).toHaveAttribute('role', 'log');
    await expect(log).toHaveAttribute('aria-live', 'off');
    await expect(log).toHaveAttribute('aria-label', ru['a11y.transcript']);

    await page.locator('.composer-textarea').fill('Составь ответ');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();
    await expect(page.locator('.artifact-pane .doc')).toBeVisible();

    // Канал смонтирован с первого рендера и не переключает aria-live: два слота.
    const channel = page.locator('.live-announcer');
    await expect(channel).toHaveCount(2);
    for (const region of await channel.all()) {
      await expect(region).toHaveAttribute('aria-live', 'polite');
      await expect(region).toHaveAttribute('aria-atomic', 'true');
    }

    // Финальный сигнал — одно объявление, а не перечисление всего ответа.
    await expect(channel.filter({ hasText: ru['a11y.ready'] })).toHaveCount(1);
    const spoken = (await channel.allTextContents()).join(' ').trim();
    await expect(spoken).not.toContain('Первый закрытый блок.');

    // Разметка канала не должна ломать axe: регион скрыт, но валиден.
    await scan(page);
  });
});

test.describe('reduced motion', () => {
  test('движение гасится, индикаторы работы сохраняются', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const server = defaultApi();
    // Задержка нужна, чтобы поймать состояние «в работе» и заглянуть в спиннер.
    server.reply('intents.process.stream', {
      delayMs: 1_500,
      json: { task_id: 'task-1', output: answerDocument() },
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.locator('.composer-textarea').fill('Составь письмо');
    await page.getByRole('button', { name: 'Отправить сообщение' }).click();

    const motion = await page.evaluate(() => {
      const root = document.querySelector('palatium-assistant')?.shadowRoot;
      if (!root) throw new Error('shadow root is missing');
      const read = (selector: string): { animation: string; transform: string } => {
        const element = root.querySelector(selector);
        if (!element) throw new Error(`${selector} is missing`);
        const style = getComputedStyle(element);
        return { animation: style.animationName, transform: style.transform };
      };
      return {
        message: read('.msg.user'),
        spinner: read('.send-btn .spin'),
      };
    });

    // Появление сообщения — движение: `fadeSlide` выключен, сдвига нет.
    expect(motion.message.animation).toBe('none');
    expect(motion.message.transform).toBe('none');
    // Спиннер — НЕ движение, а сигнал «запрос выполняется»: он обязан остаться,
    // иначе «работаю» становится неотличимо от «зависло».
    expect(motion.spinner.animation).not.toBe('none');

    // Орб ожидания при выключенном движении — статичная картинка, поэтому
    // подпись фазы перестаёт быть sr-only и показывается текстом: иначе
    // «идёт работа» не прочитать ни глазами, ни по одному лишь цвету.
    const phase = await page.locator('.msg.is-waiting [role="status"]').evaluate(element => {
      const style = getComputedStyle(element);
      return {
        position: style.position,
        clipPath: style.clipPath,
        width: element.getBoundingClientRect().width,
      };
    });
    expect(phase.position).toBe('static');
    expect(phase.clipPath).toBe('none');
    expect(phase.width).toBeGreaterThan(40);
  });

  /**
   * Иконка статуса — тоже движение, и CSS её не гасит: Lottie-web рисует своим
   * rAF-циклом, `.icon-animated { animation: none }` снимает анимацию только с
   * Lucide-фоллбека. Поэтому при выключенном движении Lottie не рендерится
   * вовсе: пользователь получает статичный Lucide-глиф, а rAF-цикл не стартует.
   *
   * Проверяется выбор рендерера, а не пиксели: насколько корректно движется
   * конкретный Lottie — свойство ассета, а не компонента.
   */
  test('иконка статуса: при выключенном движении Lottie не монтируется', async ({ page }) => {
    const document = documentWithAnimatedCallout('success');

    await page.emulateMedia({ reducedMotion: 'reduce' });
    await runStream(page, document);

    await expect(page.locator('.block-callout')).toHaveCount(1);
    await expect(page.locator('.block-callout .token-lottie')).toHaveCount(0);
    // Глиф остаётся: выключенное движение не должно прятать смысл статуса.
    const glyph = page.locator('.block-callout svg.icon-animated');
    await expect(glyph).toHaveCount(1);
    expect(await glyph.evaluate(element => element.getBoundingClientRect().width)).toBeGreaterThan(
      0
    );
  });

  test('контроль: то же место без reduced-motion идёт через Lottie', async ({ page }) => {
    // Без этого кейса предыдущий был бы зелёным и в сборке, где Lottie не
    // подключён вовсе. `no-preference` задан явно: иначе кейс зависел бы от
    // системной настройки машины («уменьшить движение» в Windows) — а гейт,
    // который краснеет от настройки ОС разработчика, ничего не проверяет (080).
    const document = documentWithAnimatedCallout('success');

    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await runStream(page, document);

    await expect(page.locator('.block-callout .token-lottie')).toHaveCount(1);
    // Lucide-фоллбек при этом не рисуется — иначе статус был бы двойным.
    await expect(page.locator('.block-callout svg.icon-animated')).toHaveCount(0);
  });
});
