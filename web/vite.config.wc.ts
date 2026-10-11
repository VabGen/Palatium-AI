import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';

const API_TARGET = 'http://127.0.0.1:8000';

/**
 * Semver берём из `package.json`, а не хардкодим: имя артефакта — часть контракта
 * доставки, и рассинхрон с версией пакета был бы тихим.
 */
const { version } = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf8')
) as { version: string };

/**
 * Сборка embeddable-виджета (`npm run build:widget`) и стенд для разработки
 * без СЭД (`npm run dev:standalone` → /standalone.html).
 *
 * IIFE single-file: СЭД подключает один `<script>`, поэтому динамические импорты
 * запрещены (`codeSplitting: false` / `inlineDynamicImports`). Chunk groups в
 * lib-режиме несовместимы со single-file — сознательно отсутствуют.
 *
 * В имени файла — версия и контент-хеш (`palatium-assistant.v0.1.0.<hash>.iife.js`).
 * Хеш делает артефакт иммутабельным: обновление виджета меняет URL, поэтому хост
 * может кэшировать файл навечно (`Cache-Control: immutable`), а SRI-дайджест —
 * зафиксировать в `release.json` (см. `scripts/widget-release.mjs`).
 */
export default defineConfig({
  plugins: [
    react({ jsxRuntime: 'automatic' }),
    {
      // Vite печатает Local: / → SPA index.html (белый #root). Стенд — standalone.html.
      name: 'redirect-root-to-standalone',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const path = req.url?.split('?', 1)[0] ?? '';
          if (path === '/' || path === '/index.html') {
            const qs = req.url?.includes('?') ? req.url.slice(req.url.indexOf('?')) : '';
            res.statusCode = 302;
            res.setHeader('Location', `/standalone.html${qs}`);
            res.end();
            return;
          }
          next();
        });
      },
    },
  ],
  define: { 'process.env.NODE_ENV': '"production"' },
  server: {
    port: 5174,
    // Явный IPv4-loopback, а не `localhost`: на Windows `localhost` разрешается в
    // `::1`, и стенд оказывается доступен только по IPv6 — снаружи (пробники,
    // Playwright, отладка из контейнера) это выглядит как «сервер не поднялся».
    host: '127.0.0.1',
    open: '/standalone.html',
    proxy: {
      '/api': { target: API_TARGET, changeOrigin: true },
      '/health': API_TARGET,
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist-widget',
    emptyOutDir: true,
    lib: {
      entry: 'src/widget.tsx',
      name: 'PalatiumAssistant',
      formats: ['iife'],
      fileName: () => `palatium-assistant.v${version}.[hash].iife.js`,
    },
    rolldownOptions: {
      // lottie-web uses direct eval; previously silenced via esbuild.logOverride.
      checks: { eval: false },
      output: {
        // Vite 8 / Rolldown: prefer codeSplitting:false over deprecated inlineDynamicImports.
        codeSplitting: false,
        assetFileNames: 'palatium-assistant.[ext]',
      },
    },
    cssCodeSplit: false,
    // Vite 8: Oxc minifier (esbuild minify is deprecated).
    minify: true,
    // Осознанно es2022 (а не es2020 как в app-сборке): целевой браузер СЭД — Chromium Edge.
    target: 'es2022',
    sourcemap: false,
    reportCompressedSize: true,
  },
});
