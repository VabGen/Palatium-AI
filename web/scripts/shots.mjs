#!/usr/bin/env node
/**
 * Снимки виджета в тёмной и светлой темах — по запросу, вне CI.
 *
 * Обёртка существует ради одной строки: `SHOTS=1 playwright test` не работает в
 * PowerShell (свой синтаксис переменных), а класть `cross-env` в зависимости ради
 * визуальной сверки — лишний пакет в supply-chain виджета. Node-скрипт задаёт
 * переменную окружения одинаково на Windows и в Linux.
 *
 * Кадры падают в `web/.shots/` (в .gitignore): сравнения с базлайном нет, это
 * материал для глаз человека после правки токенов.
 */
import { spawnSync } from 'node:child_process';

const result = spawnSync('npx', ['playwright', 'test', 'shots.spec.ts'], {
  stdio: 'inherit',
  // На Windows `npx` — это .cmd, для него нужен shell; на Unix он и так исполняемый.
  shell: process.platform === 'win32',
  env: { ...process.env, SHOTS: '1' },
});

process.exit(result.status ?? 1);
