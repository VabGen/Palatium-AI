/**
 * One-shot: pull kimi.ai light file-card glyphs from the public statics
 * bundle (FileCard `Rl(ext)` map) into `src/assets/file-icons/`.
 */
import https from 'node:https';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT = path.join(__dirname, '../src/assets/file-icons');
const BUNDLE = 'https://statics.kimi.ai/kimi-web/assets/ca2d506bc9bdc-Dk4gb-Tg.js';
/** Light-theme vars from kimi `$` map: docx=Q, xlsx=I, pdf=G, pptx=q, txt=X, image=z */
const MAP = { docx: 'Q', xlsx: 'I', pdf: 'G', pptx: 'q', txt: 'X', image: 'z' };

function get(url) {
  return new Promise((resolve, reject) => {
    https
      .get(url, res => {
        if (
          res.statusCode &&
          res.statusCode >= 300 &&
          res.statusCode < 400 &&
          res.headers.location
        ) {
          get(res.headers.location).then(resolve, reject);
          return;
        }
        const chunks = [];
        res.on('data', c => chunks.push(c));
        res.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
      })
      .on('error', reject);
  });
}

function grab(bundle, name) {
  const needles = [`,${name}=\`data:image/svg+xml`, `${name}=\`data:image/svg+xml`];
  let i = -1;
  let needle = '';
  for (const n of needles) {
    i = bundle.indexOf(n);
    if (i >= 0) {
      needle = n;
      break;
    }
  }
  if (i < 0) throw new Error(`missing var ${name}`);
  if (needle.startsWith(',')) i += 1;
  const start = bundle.indexOf('`', i) + 1;
  const end = bundle.indexOf('`', start);
  const dataUrl = bundle.slice(start, end);
  return decodeURIComponent(dataUrl.replace(/^data:image\/svg\+xml,/, ''));
}

fs.mkdirSync(OUT, { recursive: true });
const bundle = await get(BUNDLE);
for (const [kind, varName] of Object.entries(MAP)) {
  const svg = grab(bundle, varName);
  fs.writeFileSync(path.join(OUT, `${kind}.svg`), `${svg}\n`);
  console.log(`wrote ${kind}.svg (${svg.length} chars)`);
}
fs.copyFileSync(path.join(OUT, 'txt.svg'), path.join(OUT, 'generic.svg'));
console.log('wrote generic.svg (alias of txt)');
