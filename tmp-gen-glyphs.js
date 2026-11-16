const fs = require('fs');

const src = JSON.parse(
  fs.readFileSync(
    'C:/Users/Vabishchevich_H/.cursor/browser-logs/cdp-response-Runtime.evaluate-2026-11-07T03-24-27-656Z.json',
    'utf8',
  ),
).result.value;
const map = JSON.parse(src);

function parse(svg) {
  const m = svg.match(/^<svg([^>]*)>([\s\S]*)<\/svg>$/);
  const attrs = {};
  const re = /([a-zA-Z:-]+)="([^"]*)"/g;
  let a;
  while ((a = re.exec(m[1]))) attrs[a[1]] = a[2];
  const props = {};
  for (const key of [
    'fill',
    'stroke',
    'stroke-width',
    'stroke-linecap',
    'stroke-linejoin',
    'stroke-miterlimit',
    'fill-rule',
    'clip-rule',
    'preserveAspectRatio',
  ]) {
    if (attrs[key] !== undefined) props[key] = attrs[key];
  }
  return { viewBox: attrs.viewBox || '0 0 24 24', props, inner: m[2] };
}

const escapeTemplate = s =>
  s.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${');

const glyphs = {};
for (const [key, value] of Object.entries(map)) glyphs[key] = parse(value);

let out = `/* Kimi AI rail glyphs — static idle frames extracted from kimi.ai (24px grid).
   Generated: do not hand-edit geometry; re-extract from the live source instead. */

export type KimiGlyphName = keyof typeof GLYPHS;

type Glyph = { viewBox: string; props: Record<string, string>; inner: string };

const GLYPHS = {
`;
for (const [key, glyph] of Object.entries(glyphs)) {
  out += `  ${key}: {\n`;
  out += `    viewBox: ${JSON.stringify(glyph.viewBox)},\n`;
  out += `    props: ${JSON.stringify(glyph.props)},\n`;
  out += `    inner: \`${escapeTemplate(glyph.inner)}\`,\n`;
  out += `  },\n`;
}
out += `} satisfies Record<string, Glyph>;

export function KimiGlyph({
  name,
  size = 18,
  className,
}: {
  name: KimiGlyphName;
  size?: number;
  className?: string;
}) {
  const glyph = GLYPHS[name];
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width={size}
      height={size}
      viewBox={glyph.viewBox}
      className={className}
      aria-hidden
      focusable="false"
      {...glyph.props}
      dangerouslySetInnerHTML={{ __html: glyph.inner }}
    />
  );
}
`;

fs.writeFileSync('d:/project/palatium-ai/web/src/icons/kimiNavGlyphs.tsx', out);
console.log('written', Object.keys(glyphs).length, 'glyphs', out.length, 'bytes');
