import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

/**
 * Unit/component/integration контур (084) — быстрый слой пирамиды.
 *
 * Два контура намеренно разделены:
 *  - **Vitest** (`tests/**`) — секунды, jsdom, HTTP-границы мокает MSW;
 *  - **Playwright** (`e2e/**`) — минуты, настоящий Chromium, Shadow DOM/focus/axe.
 *
 * Поэтому `e2e/` здесь явно ИСКЛЮЧЁН: у Playwright свои `test()`/`describe()`, и
 * Vitest, подобрав .spec.ts, упал бы на чужом API. Раньше это было бы первым
 * сюрпризом после добавления Vitest, поэтому исключение задано явно, а не
 * «дефолтным include».
 */
export default defineConfig({
  plugins: [react({ jsxRuntime: 'automatic' })],
  test: {
    environment: 'jsdom',
    // Явные импорты `describe/it/expect` в тестах: ambient-глобалы скрывают, что
    // тест зависит от раннера, и ломают `tsc` без правки tsconfig `types`.
    globals: false,
    include: ['tests/**/*.test.{ts,tsx}'],
    exclude: ['e2e/**', 'node_modules/**', 'dist/**', 'dist-widget/**'],
    setupFiles: ['tests/setup.ts'],
    // Мок, оставшийся от предыдущего теста, — источник «мигающих» прогонов: сброс
    // обязателен, а не по желанию автора теста.
    restoreMocks: true,
    clearMocks: true,
  },
});
