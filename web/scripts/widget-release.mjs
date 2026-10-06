#!/usr/bin/env node
/**
 * Релизный манифест виджета: SRI, размеры, бюджет и валидация CEM.
 *
 * Запускается сразу после `vite build` (см. `build:widget`), потому что SRI —
 * это хеш ГОТОВОГО файла: посчитать его внутри сборки нельзя, а «прикинуть»
 * нечем — дайджест обязан совпадать байт в байт, иначе браузер отвергнет скрипт.
 *
 * Почему свой скрипт, а не плагин: нужен один артефакт (`release.json`) и три
 * проверки, которые плагины делают по отдельности. Crypto/gzip — из Node,
 * новых зависимостей ноль.
 *
 * Режимы:
 *   (по умолчанию)  собрать `release.json` + `custom-elements.json` в `dist-widget/`
 *   --verify        перепроверить, что записанный дайджест соответствует файлу
 *
 * `--verify` гоняется в CI сразу после сборки и при разборе инцидента («а это
 * точно тот артефакт?»): он сверяет `release.json` с байтами бандла и с версией
 * `package.json`. Проверять скачанный файл руками хосту не нужно — для этого
 * достаточно стандартного дайджеста (`docs/embedded-assistant.md` §6).
 */
import { createHash } from 'node:crypto';
import { copyFileSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { basename, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const DIST = join(ROOT, 'dist-widget');
const RELEASE = join(DIST, 'release.json');
const CEM_SOURCE = join(ROOT, 'custom-elements.json');
const CEM_ARTIFACT = join(DIST, 'custom-elements.json');

/**
 * Бюджет gzip, KiB. Зафиксирован в плане (`.cursor/plans/web-embed-assistant.md`,
 * W1/W7): 150 KB gzip — это то, что реально отдаётся в браузер СЭД.
 * Поднять бюджет = осознанное решение с обновлением плана, а не правка «чтобы CI был зелёным».
 */
const BUDGET_KIB = 150;

/** Кибибайт, а не «kB»: бюджет считаем в KiB, отчёт сборки печатает kB (10^3) — числа близки, но единицы разные. */
const KIB = 1024;

/** Тег элемента — дубль из `@palatium/contract`, тут как проверка CEM, а не источник истины. */
const EXPECTED_TAG = 'palatium-assistant';

/** Иммутабельный кэш безопасен ровно потому, что имя содержит контент-хеш. */
const CACHE_CONTROL = 'public, max-age=31536000, immutable';

function fail(message) {
  console.error(`[widget-release] ${message}`);
  process.exit(1);
}

function readJson(path, what) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    fail(`${what} не читается (${path}): ${error.message}`);
  }
}

function integrityOf(buffer) {
  return `sha384-${createHash('sha384').update(buffer).digest('base64')}`;
}

/**
 * Хеш в имени файла проставляет Rollup (xxhash по чанку), поэтому пересчитать его
 * из байтов нельзя — проверяем не значение, а ФОРМУ имени: она фиксирует
 * `palatium-assistant.v<version>.<hash>.iife.js`, и по ней видно, не подмешан ли
 * в каталог артефакт другой версии. Версия — non-greedy: semver содержит точки
 * (`0.1.0`), поэтому жадное `[^.]*` разобрало бы имя неверно.
 */
const BUNDLE_NAME = /^palatium-assistant\.v(?<version>.+?)\.(?<hash>[A-Za-z0-9_-]+)\.iife\.js$/;

function gzipBytes(buffer) {
  // Сжатие по умолчанию (уровень 6), а НЕ level 9: именно это число печатает сам
  // `vite build` в отчёте о размерах. Бюджет должен совпадать с тем, что видно в
  // логе сборки и записано в плане, иначе «139 KiB» и «143 kB» живут в двух мирах
  // (уровень 9 экономит ~380 байт и разошёлся бы с отчётом).
  return gzipSync(buffer).byteLength;
}

/** Ровно один IIFE-бандл: два артефакта означали бы неоднозначность для потребителя. */
function findBundle() {
  const bundles = readdirSync(DIST).filter(name => name.endsWith('.iife.js'));
  if (bundles.length === 0) fail(`в ${DIST} нет *.iife.js — сначала выполните vite build`);
  if (bundles.length > 1)
    fail(`ожидался один бандл, найдено ${bundles.length}: ${bundles.join(', ')}`);
  return join(DIST, bundles[0]);
}

/** CEM обязан быть валидным и содержать контракт элемента — иначе артефакт неполон. */
function validateManifest() {
  const manifest = readJson(CEM_SOURCE, 'custom-elements.json');
  const declarations = manifest.modules?.flatMap(module => module.declarations ?? []) ?? [];
  const element = declarations.find(
    declaration => declaration.customElement === true && declaration.tagName === EXPECTED_TAG
  );
  if (!element)
    fail(`в custom-elements.json нет объявления <${EXPECTED_TAG}> — выполните \`npm run cem\``);
  return { manifest, tagName: element.tagName };
}

function release() {
  const { version } = readJson(join(ROOT, 'package.json'), 'package.json');
  const bundlePath = findBundle();
  const buffer = readFileSync(bundlePath);
  const bytes = buffer.byteLength;
  const gzipped = gzipBytes(buffer);
  const gzipKib = gzipped / KIB;

  if (gzipKib > BUDGET_KIB) {
    fail(
      `бюджет пробит: ${gzipKib.toFixed(2)} KiB gzip > ${BUDGET_KIB} KiB. ` +
        'Уменьшите вес или осознанно поднимите BUDGET_KIB вместе с планом (W1/2.4).'
    );
  }

  const { tagName } = validateManifest();
  copyFileSync(CEM_SOURCE, CEM_ARTIFACT);

  const file = basename(bundlePath);
  const releaseManifest = {
    name: 'palatium-assistant',
    version,
    tagName,
    file,
    integrity: integrityOf(buffer),
    algorithm: 'sha384',
    bytes,
    gzipBytes: gzipped,
    budgetKib: BUDGET_KIB,
    cacheControl: CACHE_CONTROL,
    customElementsManifest: basename(CEM_ARTIFACT),
  };
  writeFileSync(RELEASE, `${JSON.stringify(releaseManifest, null, 2)}\n`, 'utf8');

  const budgetLine = `${gzipKib.toFixed(2)} / ${BUDGET_KIB} KiB gzip (${(
    (gzipKib / BUDGET_KIB) *
    100
  ).toFixed(1)}% бюджета)`;
  console.log('[widget-release] артефакты готовы');
  console.log(`  файл       ${file}`);
  console.log(`  версия     v${version}`);
  console.log(`  raw        ${(bytes / 1024).toFixed(2)} KiB`);
  console.log(`  бюджет     ${budgetLine}`);
  console.log(`  integrity  ${releaseManifest.integrity}`);
  console.log(`  заголовок  Cache-Control: ${CACHE_CONTROL}`);
  console.log(`  манифест   release.json + ${releaseManifest.customElementsManifest}`);
}

/**
 * Перепроверка артефакта по `release.json`.
 *
 * Считается дважды: дайджест файла и его размер. Размер ловит усечённую загрузку,
 * дайджест — подмену содержимого; вместе они дают то, что обещает `integrity` в HTML.
 */
function verify() {
  const manifest = readJson(RELEASE, 'release.json');
  const bundlePath = join(DIST, manifest.file);

  try {
    statSync(bundlePath);
  } catch {
    fail(`нет файла ${manifest.file} рядом с release.json — артефакт неполон`);
  }

  const buffer = readFileSync(bundlePath);
  const actual = integrityOf(buffer);
  if (actual !== manifest.integrity) {
    fail(`integrity не совпадает: в release.json ${manifest.integrity}, у файла ${actual}`);
  }
  if (buffer.byteLength !== manifest.bytes) {
    fail(`размер не совпадает: ожидалось ${manifest.bytes} байт, получено ${buffer.byteLength}`);
  }
  const parsed = BUNDLE_NAME.exec(manifest.file);
  if (!parsed?.groups) {
    fail(
      `имя ${manifest.file} не соответствует схеме palatium-assistant.v<version>.<hash>.iife.js`
    );
  }
  if (parsed.groups.version !== manifest.version) {
    fail(`в имени файла версия v${parsed.groups.version}, а в release.json v${manifest.version}`);
  }
  const { version } = readJson(join(ROOT, 'package.json'), 'package.json');
  if (manifest.version !== version) {
    fail(`версия в release.json (v${manifest.version}) расходится с package.json (v${version})`);
  }

  console.log(`[widget-release] ${manifest.file}: integrity подтверждён (${actual})`);
}

if (process.argv.includes('--verify')) verify();
else release();
