/**
 * Nested list rows carry their level as a text prefix (the content contract has no
 * level field). Printing the prefix made the user see two markers — "• · Подпункт".
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import type { ContentDocument } from '../../src/types/contentDocument';

function docWithNestedList(): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks: [
      {
        type: 'list',
        style: 'unordered',
        items: [{ text: 'Пункт' }, { text: '· Подпункт' }],
      },
    ],
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
      interaction: 'none',
    },
  };
}

describe('nested list rendering', () => {
  it('decodes the nesting prefix instead of printing it', () => {
    const { container } = render(<BlockRenderer document={docWithNestedList()} />);

    const rows = container.querySelectorAll('.block-list li');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toBe('Пункт');
    expect(rows[1].textContent).toBe('Подпункт');
    expect(rows[1].classList.contains('nested')).toBe(true);
    expect(container.textContent).not.toContain('·');
  });
});
