/**
 * Inject Brand Book @font-face into document.head so Shadow DOM inherits faces.
 * Companion files: `<script-dir>/fonts/*.woff2` (copied from `public/fonts` on widget build).
 * Absolute `/fonts/...` works for Vite SPA / standalone; widget uses script-relative base.
 */

const STYLE_ID = 'palatium-kimi-fonts';

function fontBaseHref(): string {
  // Dev / SPA: files from `public/fonts` at site root.
  if (import.meta.env.DEV) {
    return `${window.location.origin}/`;
  }
  // Production IIFE: companion `fonts/` next to the assistant bundle.
  // Do not use `import.meta.url` — Vite IIFE replaces it with `{}`.
  const current = document.currentScript as HTMLScriptElement | null;
  const fromCurrent = current?.src && /palatium-assistant/i.test(current.src) ? current.src : null;
  const fromDom = Array.from(document.getElementsByTagName('script'))
    .map(s => s.src)
    .find(src => /palatium-assistant/i.test(src));
  const scriptSrc = fromCurrent ?? fromDom;
  if (scriptSrc) return new URL('.', scriptSrc).href;
  return `${window.location.origin}/`;
}

function fontFaceCss(base: string): string {
  const u = (name: string) => new URL(`fonts/${name}`, base).href;
  return `
@font-face{font-family:'Inter Variable';font-style:normal;font-display:swap;font-weight:100 900;src:url('${u('inter-latin-wght-normal.woff2')}') format('woff2-variations');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Inter Variable';font-style:normal;font-display:swap;font-weight:100 900;src:url('${u('inter-latin-ext-wght-normal.woff2')}') format('woff2-variations');unicode-range:U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,U+2C60-2C7F,U+A720-A7FF}
@font-face{font-family:'Inter Variable';font-style:normal;font-display:swap;font-weight:100 900;src:url('${u('inter-cyrillic-wght-normal.woff2')}') format('woff2-variations');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}
@font-face{font-family:'Geist';font-style:normal;font-display:swap;font-weight:400;src:url('${u('geist-latin-400-normal.woff2')}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Geist';font-style:normal;font-display:swap;font-weight:500;src:url('${u('geist-latin-500-normal.woff2')}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Geist';font-style:normal;font-display:swap;font-weight:600;src:url('${u('geist-latin-600-normal.woff2')}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Geist';font-style:normal;font-display:swap;font-weight:400;src:url('${u('geist-cyrillic-400-normal.woff2')}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}
@font-face{font-family:'Geist';font-style:normal;font-display:swap;font-weight:500;src:url('${u('geist-cyrillic-500-normal.woff2')}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}
@font-face{font-family:'Geist';font-style:normal;font-display:swap;font-weight:600;src:url('${u('geist-cyrillic-600-normal.woff2')}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}
@font-face{font-family:'Geist Mono';font-style:normal;font-display:swap;font-weight:400;src:url('${u('geist-mono-latin-400-normal.woff2')}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Geist Mono';font-style:normal;font-display:swap;font-weight:500;src:url('${u('geist-mono-latin-500-normal.woff2')}') format('woff2');unicode-range:U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD}
@font-face{font-family:'Geist Mono';font-style:normal;font-display:swap;font-weight:400;src:url('${u('geist-mono-cyrillic-400-normal.woff2')}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}
@font-face{font-family:'Geist Mono';font-style:normal;font-display:swap;font-weight:500;src:url('${u('geist-mono-cyrillic-500-normal.woff2')}') format('woff2');unicode-range:U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116}
`.trim();
}

/** Idempotent: safe to call from widget connect and SPA boot. */
export function injectKimiFonts(): void {
  if (typeof document === 'undefined') return;
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement('style');
  style.id = STYLE_ID;
  style.textContent = fontFaceCss(fontBaseHref());
  document.head.appendChild(style);
}
