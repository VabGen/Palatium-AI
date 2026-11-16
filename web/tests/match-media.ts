/**
 * matchMedia-заглушка для jsdom (084).
 *
 * Зачем: `lottie-react` в эффекте читает `window.matchMedia` (в т.ч. для
 * `prefers-reduced-motion`), а jsdom его не реализует — любой рендер
 * анимированной иконки падает с «window.matchMedia is not a function».
 * Это ограничение окружения, а не поведение продукта: сам контракт
 * «анимация уважает prefers-reduced-motion» проверяется в Playwright
 * (`e2e/a11y.spec.ts` → `emulateMedia({ reducedMotion: 'reduce' })`), где
 * media-запросы настоящие.
 *
 * Заглушка отвечает `matches: false` — то есть «движение разрешено»: тесты
 * проверяют выбор рендерера (Lottie vs Lucide), а не ветку reduced-motion.
 * Подписки не хранятся: в jsdom media-запрос не меняется, доставлять событие
 * нечего — копить слушатели значило бы держать утечку в тестовом окружении.
 */
const NOOP = (): void => undefined;

export function installMatchMediaStub(): void {
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    writable: true,
    value(query: string): MediaQueryList {
      return {
        matches: false,
        media: query,
        onchange: null,
        addEventListener: NOOP,
        removeEventListener: NOOP,
        addListener: NOOP,
        removeListener: NOOP,
        dispatchEvent: () => false,
      } as unknown as MediaQueryList;
    },
  });
}
