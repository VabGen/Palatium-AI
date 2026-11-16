import { render } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TokenIcon } from '../../src/icons/TokenIcon';

describe('TokenIcon', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('renders a known token as svg', () => {
    const { container } = render(<TokenIcon token="document" />);
    expect(container.querySelector('svg')).not.toBeNull();
  });

  it('exposes token-icon class and size var for first-line centering', () => {
    const { container } = render(<TokenIcon token="search" size={18} />);
    const icon = container.querySelector('.token-icon');
    expect(icon).not.toBeNull();
    expect(icon).toHaveStyle({ '--token-icon-size': '18px' });
  });

  it('falls back and warns for unknown names', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const { container } = render(<TokenIcon token="not_a_real_icon" turnId="turn-1" />);
    expect(container.querySelector('svg')).not.toBeNull();
    expect(warn).toHaveBeenCalledWith(
      '[TokenIcon] unknown icon name; using fallback',
      expect.objectContaining({ name: 'not_a_real_icon', turnId: 'turn-1' })
    );
  });

  it('renders nothing when token is empty', () => {
    const { container } = render(<TokenIcon token={null} />);
    expect(container.querySelector('svg')).toBeNull();
  });
});

/**
 * Regression: `raw in TOKEN_MAP` walked the prototype chain, so a stream payload of
 * `token="constructor"` resolved to `Object` and crashed the tree.
 * Own-property lookup keeps an untrusted name on the fallback path.
 */
describe('TokenIcon prototype-chain safety', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  for (const hostile of ['constructor', '__proto__', 'toString', 'valueOf', 'hasOwnProperty']) {
    it(`falls back for ${hostile} instead of resolving an inherited property`, () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      const { container } = render(<TokenIcon token={hostile} turnId="turn-9" />);

      expect(container.querySelector('svg')).not.toBeNull();
      expect(warn).toHaveBeenCalledWith(
        '[TokenIcon] unknown icon name; using fallback',
        expect.objectContaining({ name: hostile.toLowerCase(), fallback: 'info' })
      );
      expect(container.innerHTML).not.toContain('Object');
    });
  }

  it('falls back for a hostile name even with animated enabled', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
    const hostile = render(<TokenIcon token="constructor" animated />);
    const fallback = render(<TokenIcon token="info" animated />);

    // The fallback token is `info`, and `info` *is* animated — so a Lottie here is the
    // fallback's own animation, never a prototype lookup. The contract is: no crash.
    expect(hostile.container.firstElementChild?.tagName).toBe(
      fallback.container.firstElementChild?.tagName
    );
    expect(hostile.container.firstElementChild?.classList.contains('token-lottie')).toBe(
      fallback.container.firstElementChild?.classList.contains('token-lottie')
    );
    expect(warn).toHaveBeenCalledWith(
      '[TokenIcon] unknown icon name; using fallback',
      expect.objectContaining({ name: 'constructor' })
    );
  });

  it('renders nothing for undefined and empty string', () => {
    expect(render(<TokenIcon token={undefined} />).container.firstElementChild).toBeNull();
    expect(render(<TokenIcon token="" />).container.firstElementChild).toBeNull();
  });
});

/**
 * Animation policy: tone callouts may Lottie; action/content tokens stay on
 * official Kimi glyphs (CSS pulse only when animated).
 */
describe('TokenIcon animation policy', () => {
  const LOTTIE_TOKENS = ['info', 'success', 'warning', 'danger'] as const;

  const GLYPH_ONLY_TOKENS = [
    'calendar',
    'mail',
    'search',
    'document',
    'user',
    'users',
    'chart',
    'link',
    'edit',
    'settings',
    'check',
    'x',
    'clock',
    'shield',
  ] as const;

  for (const token of LOTTIE_TOKENS) {
    it(`animated ${token} → lottie`, () => {
      const { container } = render(<TokenIcon token={token} animated />);
      expect(container.firstElementChild?.classList.contains('token-lottie')).toBe(true);
    });

    it(`static ${token} → kimi glyph svg`, () => {
      const { container } = render(<TokenIcon token={token} />);
      const svg = container.querySelector('svg');
      expect(svg).not.toBeNull();
      expect(svg?.getAttribute('class') ?? '').not.toContain('icon-animated');
    });
  }

  for (const token of GLYPH_ONLY_TOKENS) {
    it(`animated ${token} stays kimi glyph (icon-animated class only)`, () => {
      const { container } = render(<TokenIcon token={token} animated />);
      expect(container.querySelector('.token-lottie')).toBeNull();
      expect(container.querySelector('svg')?.getAttribute('class') ?? '').toContain(
        'icon-animated'
      );
    });
  }
});
