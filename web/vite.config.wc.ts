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
 * запрещены (`inlineDynamicImports`). `manualChunks` в lib-режиме несовместим со
 * single-file — сознательно отсутствует.
 *
 * В имени файла — версия и контент-хеш (`palatium-assistant.v0.1.0.<hash>.iife.js`).
 * Хеш делает артефакт иммутабельным: обновление виджета меняет URL, поэтому хост
 * может кэшировать файл навечно (`Cache-Control: immutable`), а SRI-дайджест —
 * зафиксировать в `release.json` (см. `scripts/widget-release.mjs`).
 */
export default defineConfig({
  plugins: [react({ jsxRuntime: 'automatic' })],
  define: { 'process.env.NODE_ENV': '"production"' },
  server: {
    port: 5174,
    // Явный IPv4-loopback, а не `localhost`: на Windows `localhost` разрешается в
    // `::1`, и стенд оказывается доступен только по IPv6 — снаружи (пробники,
    // Playwright, отладка из контейнера) это выглядит как «сервер не поднялся».
    host: '127.0.0.1',
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
    rollupOptions: {
      output: {
        inlineDynamicImports: true,
        assetFileNames: 'palatium-assistant.[ext]',
      },
    },
    cssCodeSplit: false,
    minify: 'esbuild',
    // Осознанно es2022 (а не es2020 как в app-сборке): целевой браузер СЭД — Chromium Edge.
    target: 'es2022',
    sourcemap: false,
    reportCompressedSize: true,
  },
  esbuild: {
    legalComments: 'none',
  },
});
