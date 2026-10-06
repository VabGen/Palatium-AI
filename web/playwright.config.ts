import { defineConfig, devices } from '@playwright/test';

/**
 * E2E-контур виджета (W8).
 *
 * Запускается против `standalone.html` — того же стенда, что видит человек при
 * разработке без СЭД. Backend НЕ нужен: все `/api/**` перехватываются
 * (`e2e/mock-server.ts`), поэтому набор детерминирован и не требует поднятого
 * стека. `standalone.html` поднимает dev-сервер Vite на 5174 (см. `vite.config.wc.ts`).
 *
 * Почему dev-сервер, а не `vite preview` собранного бандла: тесты должны видеть
 * исходные модули (стек ошибок читается), а артефакт релиза проверяется отдельно
 * (`build:widget` + `verify:widget`). Контракт элемента от этого не меняется:
 * `widget.tsx` — тот же вход.
 */
const PORT = 5174;
const BASE_URL = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: 'e2e',
  // Полная параллельность безопасна: каждый тест изолирован своим контекстом и
  // своими моками, общего состояния между файлами нет.
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : [['list']],
  timeout: 30_000,
  expect: { timeout: 5_000 },

  use: {
    baseURL: BASE_URL,
    trace: 'on-first-retry',
    // Скриншот при падении — дешевле, чем перезапуск с трейсом на локальной машине.
    screenshot: 'only-on-failure',
    viewport: { width: 1280, height: 800 },
  },

  projects: [
    {
      name: 'chromium',
      // Целевой браузер СЭД — Chromium (Edge); кастомные элементы и Shadow DOM
      // проверяются именно там, где виджет будет жить.
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  webServer: {
    command: 'npm run dev:standalone',
    url: `${BASE_URL}/standalone.html`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    stdout: 'ignore',
    stderr: 'pipe',
  },
});
