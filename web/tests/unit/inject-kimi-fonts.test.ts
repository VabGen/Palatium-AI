import { afterEach, describe, expect, it } from 'vitest';
import { injectKimiFonts } from '../../src/lib/injectKimiFonts';

describe('injectKimiFonts', () => {
  afterEach(() => {
    document.getElementById('palatium-kimi-fonts')?.remove();
  });

  it('injects Inter Variable, Geist display, and Geist Mono faces once', () => {
    injectKimiFonts();
    injectKimiFonts();
    const nodes = document.querySelectorAll('#palatium-kimi-fonts');
    expect(nodes).toHaveLength(1);
    const css = nodes[0]?.textContent ?? '';
    expect(css).toContain('Inter Variable');
    expect(css).toContain("font-family:'Geist'");
    expect(css).toContain('Geist Mono');
    expect(css).toContain('inter-latin-wght-normal.woff2');
    expect(css).toContain('geist-latin-600-normal.woff2');
  });
});
