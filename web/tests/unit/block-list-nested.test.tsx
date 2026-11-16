/**
 * Nested list rows: prefer ``ListItem.level``; legacy ``· `` prefix still decoded.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import type { ContentDocument, ListItem } from '../../src/types/contentDocument';

function docWithNestedList(items: ListItem[]): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks: [
      {
        type: 'list',
        style: 'unordered',
        items,
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
    const { container } = render(
      <BlockRenderer document={docWithNestedList([{ text: 'Пункт' }, { text: '· Подпункт' }])} />
    );

    const rows = container.querySelectorAll('.block-list li');
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toBe('Пункт');
    expect(rows[1].textContent).toBe('Подпункт');
    expect(rows[1].classList.contains('nested')).toBe(true);
    expect(container.textContent).not.toContain('·');
  });

  it('uses typed level without a text prefix', () => {
    const { container } = render(
      <BlockRenderer
        document={docWithNestedList([{ text: 'Пункт' }, { text: 'Подпункт', level: 1 }])}
      />
    );
    const nested = container.querySelector('.block-list-item.nested.level-1');
    expect(nested?.textContent).toBe('Подпункт');
  });
});
