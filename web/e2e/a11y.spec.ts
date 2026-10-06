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
import {
  answerDocument,
  defaultApi,
  openWidget,
  stepUpChallenge,
  stubSessionSocket,
  toolCard,
} from './fixtures';

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
    server.reply('intents.process', {
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

    await page.getByRole('textbox').fill('Отправь письмо');
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

    // Стартовая точка задаётся явно. Браузер запоминает «место, где остановился
    // Tab» на момент загрузки, а виджет к тому времени ещё дорисовывается, —
    // без якоря обход начинается не с первого контроля. Якорь на последнем
    // контроле страницы-хоста заодно проверяет главное: последовательность не
    // обрывается на границе Shadow DOM, а продолжается внутри виджета.
    await page.locator('#btn-expand').focus();
    const visited = await tabInto(page, 7);

    // Порядок = порядок в разметке: шапка → подсказки → блок ввода.
    // `.send-btn` в списке нет: пустой ввод делает кнопку disabled, а такие
    // элементы в обход не попадают.
    expect(visited.map(item => `${item.tag}.${item.className.split(' ')[0]}`)).toEqual([
      'button.toolbar-btn',
      'button.toolbar-btn',
      'button.suggestion',
      'button.suggestion',
      'button.memory-toggle',
      'button.attach-btn',
      'textarea.composer-textarea',
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
    server.reply('intents.process', { json: { task_id: 'task-1', output: answerDocument() } });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.getByRole('textbox').fill('Составь письмо');
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

test.describe('reduced motion', () => {
  test('движение гасится, индикаторы работы сохраняются', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const server = defaultApi();
    // Задержка нужна, чтобы поймать состояние «в работе» и заглянуть в спиннер.
    server.reply('intents.process', {
      delayMs: 1_500,
      json: { task_id: 'task-1', output: answerDocument() },
    });
    await stubSessionSocket(page);
    await server.install(page);
    await openWidget(page);

    await page.getByRole('textbox').fill('Составь письмо');
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
  });
});
