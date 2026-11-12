/**
 * K1 gate (plans/kimi-full-redesign.md): raw #hex only in tokens.css.
 * Comments are stripped before the scan.
 */
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const SRC = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', 'src');
const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const ALLOW_BASENAMES = new Set(['tokens.css']);
/**
 * Deliberate exceptions: third-party brand marks and catalog fixtures carry
 * their own palettes (Gmail red, Excel green, …). Those hexes are data, not
 * design tokens — they never reach product chrome. Everything rendering with
 * them does so through `PluginLogo` / fixture fields, not hardcoded CSS.
 */
const ALLOW_PATHS = [
  path.join('mocks') + path.sep,
  path.join('components', 'ui', 'PluginLogo.tsx'),
];

async function* walk(dir) {
  for (const ent of await readdir(dir, { withFileTypes: true })) {
    const full = path.join(dir, ent.name);
    if (ent.isDirectory()) yield* walk(full);
    else if (/\.(css|tsx|ts)$/.test(ent.name)) yield full;
  }
}

function stripComments(source) {
  return source.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:])\/\/.*$/gm, '$1');
}

const violations = [];
for await (const file of walk(SRC)) {
  const rel = path.relative(SRC, file);
  if (ALLOW_BASENAMES.has(path.basename(file))) continue;
  if (ALLOW_PATHS.some(p => rel.startsWith(p))) continue;
  const text = stripComments(await readFile(file, 'utf8'));
  for (const [index, line] of text.split('\n').entries()) {
    HEX.lastIndex = 0;
    if (!HEX.test(line)) continue;
    HEX.lastIndex = 0;
    const hits = line.match(HEX)?.join(', ') ?? '';
    violations.push(`${path.relative(SRC, file)}:${index + 1}: ${hits}`);
  }
}

if (violations.length > 0) {
  console.error('Kimi hex drift: raw #hex outside tokens.css:\n' + violations.join('\n'));
  process.exit(1);
}

console.log('check-kimi-hex: ok');
