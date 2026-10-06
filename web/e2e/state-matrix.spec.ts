/**
 * Исполнение матрицы состояний (W8).
 *
 * Этот файл — только интерпретатор: данные и требования живут в
 * `state-matrix.ts`. Падение здесь читается как «кадр X не показал Y», а не
 * «упал селектор» — поэтому имя теста собирается из id и заголовка кадра.
 */
import { expect, test, type Locator, type Page } from '@playwright/test';
import {
  ASSISTANT,
  defaultApi,
  findEnglishLeaks,
  openWidget,
  stubSessionSocket,
  visibleStrings,
} from './fixtures';
import type { MockServer } from './mock-server';
import { STATE_MATRIX, stateId, type Check, type WidgetState } from './state-matrix';

/**
 * Пустой селектор означает сам элемент `<palatium-assistant>`.
 * Нужно для проверок состояния ХОСТА (`[collapsed]`, `data-theme`) и его токенов:
 * это атрибуты элемента, а не элемент внутри Shadow DOM.
 */
function target(page: Page, selector: string): Locator {
  return selector === '' ? page.locator(ASSISTANT) : page.locator(selector).first();
}

async function runCheck(page: Page, check: Check): Promise<void> {
  switch (check.kind) {
    case 'text':
      await expect(target(page, check.selector)).toContainText(check.contains);
      return;
    case 'visible':
      await expect(target(page, check.selector)).toBeVisible();
      return;
    case 'hidden':
      await expect(target(page, check.selector)).toBeHidden();
      return;
    case 'count':
      await expect(page.locator(check.selector)).toHaveCount(check.count);
      return;
    case 'attr':
      if (check.value === undefined) {
        await expect(target(page, check.selector)).toHaveAttribute(check.name);
      } else {
        await expect(target(page, check.selector)).toHaveAttribute(check.name, check.value);
      }
      return;
    case 'disabled':
      await expect(target(page, check.selector)).toBeDisabled();
      return;
    case 'cssVar': {
      const value = await target(page, check.selector).evaluate(
        (element, name) => getComputedStyle(element).getPropertyValue(name).trim(),
        check.name
      );
      expect(value, `CSS-переменная ${check.name}`).toBe(check.value);
      return;
    }
    case 'noEnglish': {
      // Известные непереведённые остатки: только имена продукта (`Palatium`, `IdP`) —
      // они одинаковы в обоих словарях и в проверку не попадают.
      const leaks = findEnglishLeaks(await visibleStrings(page));
      expect(leaks, 'строки остались на английском при lang="ru"').toEqual([]);
      return;
    }
  }
}

/**
 * Привести виджет в состояние кадра.
 *
 * Порядок обязателен: моки и WS ставятся ДО `goto` (иначе первый же запрос уйдёт
 * в реальный backend), `#palatium-ready` ждётся из `addInitScript`.
 */
async function arrange(page: Page, state: WidgetState): Promise<MockServer> {
  const server = defaultApi();
  for (const script of state.api) server.reply(script.key, ...script.replies);
  if (state.turns) server.always('sessions.turns', { json: { items: state.turns } });

  await stubSessionSocket(page);
  await server.install(page);
  await openWidget(page);
  if (state.drive) await state.drive(page);
  return server;
}

test.describe('матрица состояний (state-matrix.ts)', () => {
  for (const state of STATE_MATRIX) {
    test(stateId(state), async ({ page }) => {
      const server = await arrange(page, state);

      for (const check of state.checks) await runCheck(page, check);

      // Виджет не имеет права ходить в незамоканные эндпоинты: любой такой вызов —
      // либо новая зависимость от API, либо опечатка в URL.
      expect(
        server.unmatched.map(call => `${call.method} ${call.path}`),
        'незамоканные вызовы API'
      ).toEqual([]);
    });
  }
});
