/**
 * Canvas-заглушка для jsdom (084).
 *
 * Зачем: `lottie-web` (через `lottie-react` в иконках `TokenIcon`) при ИМПОРТЕ
 * модуля создаёт `<canvas>` и берёт 2D-контекст, чтобы выбрать способ рендера.
 * jsdom `getContext('2d')` не реализует — возвращает `null` и пишет в stderr
 * «Not implemented», после чего lottie падает на `fillStyle` от `null`. Итог:
 * любой компонент, доходящий до `TokenIcon`, невозможно даже отрендерить.
 *
 * Почему заглушка, а не `canvas` (node-canvas): тесты не проверяют пиксели
 * анимации, поэтому настоящий растеризатор — нативная зависимость с тулчейном
 * сборки в CI ради нуля проверок (025, YAGNI). Заглушка закрывает ровно одну
 * операцию — «контекст существует и принимает свойства».
 *
 * Ограничение осознанное и документировано (017): assertion'ы на canvas в этом
 * окружении невалидны, их место — Playwright, где canvas настоящий.
 */

type Context2D = CanvasRenderingContext2D;

function createContext(canvas: HTMLCanvasElement): Context2D {
  const store: Record<string, unknown> = { canvas };
  const methods = new Map<string, () => undefined>();

  return new Proxy(store, {
    get(target, property): unknown {
      if (property in target) return target[property as string];
      // Метод отдаётся стабильным по ссылке: lottie сравнивает обработчики между
      // кадрами, и новый function на каждый доступ ломал бы эти сравнения.
      const existing = methods.get(String(property));
      if (existing) return existing;
      const stub = (): undefined => undefined;
      methods.set(String(property), stub);
      return stub;
    },
    set(target, property, value): boolean {
      target[property as string] = value;
      return true;
    },
  }) as unknown as Context2D;
}

/** Ставится из `tests/setup.ts` один раз на файл. */
export function installCanvasStub(): void {
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    writable: true,
    value(this: HTMLCanvasElement, contextId: string): Context2D | null {
      return contextId === '2d' ? createContext(this) : null;
    },
  });
}
