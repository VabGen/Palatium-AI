import { expect, test } from '@playwright/test';
import { answerDocument, defaultApi, openWidget, stubSessionSocket } from './fixtures';

/**
 * Lottie-ассеты статусных иконок в реальном браузере.
 *
 * Здесь проверяется то, что unit-тест проверить не может: jsdom не считает SVG,
 * поэтому «формат кейфреймов верный» и «иконка что-то нарисовала» — разные
 * утверждения. Пустой `<path>` без `d` уже случался при формально валидном JSON.
 */
const TONES = ['info', 'success', 'warning', 'danger'] as const;

async function runWithCallouts(
  page: import('@playwright/test').Page,
  options: { reuseWidget?: boolean } = {}
) {
  const document = answerDocument();
  document.blocks = TONES.map(tone => ({
    type: 'callout' as const,
    tone,
    icon: tone,
    body: `Проверка ${tone}.`,
  }));

  const server = defaultApi();
  server.reply('intents.process.stream', { json: { task_id: 'task-1', output: document } });
  await stubSessionSocket(page);
  await server.install(page);
  // `reuseWidget` — когда виджет уже открыт и в него установлен сэмплер кадров.
  if (!options.reuseWidget) await openWidget(page);
  await page.locator('.composer-textarea').fill('Составь письмо');
  await page.getByRole('button', { name: 'Отправить сообщение' }).click();
  await expect(page.locator('.block-callout')).toHaveCount(TONES.length);
}

/** Геометрия всех анимированных иконок на странице, по порядку блоков. */
async function readIcons(page: import('@playwright/test').Page) {
  return page.evaluate(() => {
    const root = document.querySelector('palatium-assistant')?.shadowRoot;
    const icons = [...(root?.querySelectorAll('.block-callout .token-lottie') ?? [])];
    return icons.map(icon => {
      const group = icon.querySelector('svg > g > g') as SVGGElement | null;
      const path = icon.querySelector('path');
      return {
        outline: (path?.getAttribute('d') ?? '').length,
        hidden: [...icon.querySelectorAll('g')].filter(
          candidate => (candidate as SVGGElement).style.display === 'none'
        ).length,
        transform: group?.getAttribute('transform') ?? null,
        opacity: group?.style.opacity ?? null,
      };
    });
  });
}

test.describe('lottie status assets', () => {
  test('каждая статусная иконка рисует контур', async ({ page }) => {
    // `no-preference` явно: иначе кейс зависел бы от системной настройки машины.
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await runWithCallouts(page);

    const icons = await readIcons(page);
    expect(icons).toHaveLength(TONES.length);
    for (const [index, icon] of icons.entries()) {
      expect(icon.outline, `${TONES[index]}: пустой path — иконка невидима`).toBeGreaterThan(0);
      // Скрытая группа = `opacity`, схлопнутая в 0 (симптом `display: none`).
      expect(icon.hidden, `${TONES[index]}: группа скрыта`).toBe(0);
      // NaN вырождает слой в `matrix(-9999.99, …)`.
      expect(icon.transform ?? '', `${TONES[index]}: вырожденный transform`).not.toContain('-9999');
    }
  });

  test('иконки действительно двигаются, а не стоят на одном кадре', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    await openWidget(page);

    // Анимация одноразовая (WCAG 2.2.2, `loop={false}`), поэтому сэмплер ставится
    // ДО ответа: опрос после рендера успел бы только на последний кадр.
    await page.evaluate(() => {
      const frames: string[] = [];
      (window as unknown as { __lottieFrames: string[] }).__lottieFrames = frames;
      const tick = () => {
        const root = document.querySelector('palatium-assistant')?.shadowRoot;
        const icons = [...(root?.querySelectorAll('.block-callout .token-lottie') ?? [])];
        if (icons.length > 0) {
          frames.push(
            icons
              .map(icon => {
                const group = icon.querySelector('svg > g > g') as SVGGElement | null;
                return `${group?.getAttribute('transform') ?? ''}/${group?.style.opacity ?? ''}`;
              })
              .join('|')
          );
        }
        requestAnimationFrame(tick);
      };
      requestAnimationFrame(tick);
    });

    await runWithCallouts(page, { reuseWidget: true });
    await page.waitForTimeout(1_200);

    const unique = await page.evaluate(
      () => new Set((window as unknown as { __lottieFrames: string[] }).__lottieFrames).size
    );
    expect(unique, 'кадры не меняются — анимация не идёт').toBeGreaterThan(1);
  });
});
