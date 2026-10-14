import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Final ordered lists use a document-scoped CSS counter (not per-ol reset).
 * Regression for UI showing "1. 1. 1. 1." when ListBlocks are split.
 */
describe('ordered list counter CSS contract', () => {
  const css = readFileSync(resolve(__dirname, '../../src/styles.css'), 'utf8');

  it('resets the item counter once on .doc-blocks', () => {
    const docBlocks = css.match(/\.doc-blocks\s*\{[^}]*\}/s);
    expect(docBlocks?.[0]).toMatch(/counter-reset:\s*item/);
  });

  it('does not reset the counter on each .block-list.style-ordered', () => {
    const orderedRule = css.match(/\.block-list\.style-ordered\s*\{[^}]*\}/s);
    // Rule may be absent or only hold non-reset properties; must not reset.
    if (orderedRule) {
      expect(orderedRule[0]).not.toMatch(/counter-reset/);
    }
    expect(css).toMatch(/\.block-list\.style-ordered li\s*\{[^}]*counter-increment:\s*item/s);
    expect(css).toMatch(/\.block-list\.style-ordered li::before\s*\{[^}]*counter\(item\)/s);
  });
});
