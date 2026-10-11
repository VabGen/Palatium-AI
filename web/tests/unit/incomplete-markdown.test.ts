import { describe, expect, it } from 'vitest';

import { closeIncompleteMarkdown } from '../../src/lib/incompleteMarkdown';

describe('closeIncompleteMarkdown', () => {
  it('closes unclosed bold', () => {
    expect(closeIncompleteMarkdown('This is **bold')).toBe('This is **bold**');
  });

  it('closes unclosed inline code', () => {
    expect(closeIncompleteMarkdown('use `code')).toBe('use `code`');
  });

  it('closes unclosed fence', () => {
    expect(closeIncompleteMarkdown('```ts\nconst x = 1')).toContain('```');
    expect(closeIncompleteMarkdown('```ts\nconst x = 1').endsWith('```')).toBe(true);
  });

  it('closes unclosed link bracket', () => {
    expect(closeIncompleteMarkdown('see [link')).toBe('see [link]');
  });

  it('leaves complete markdown unchanged', () => {
    const complete = '**bold** and `code` and [a](https://ex.com)';
    expect(closeIncompleteMarkdown(complete)).toBe(complete);
  });
});
