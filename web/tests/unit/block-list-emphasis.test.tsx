/**
 * List emphasis chrome: collapse 「Title — Title」 when text duplicates emphasis.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BlockRenderer } from '../../src/components/BlockRenderer';
import type { ContentDocument, ListItem } from '../../src/types/contentDocument';

function docWithList(items: ListItem[]): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks: [{ type: 'list', style: 'unordered', items }],
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
      interaction: 'none',
    },
  };
}

describe('list emphasis display', () => {
  it('does not repeat emphasis when text is the same title', () => {
    const { container } = render(
      <BlockRenderer
        document={docWithList([
          {
            text: 'Субъективность заключений',
            emphasis: 'Субъективность заключений',
          },
        ])}
      />
    );
    const row = container.querySelector('.block-list-item');
    expect(row?.textContent).toBe('Субъективность заключений');
    expect(row?.textContent).not.toContain('—');
  });

  it('keeps title — body when the body adds detail', () => {
    const { container } = render(
      <BlockRenderer
        document={docWithList([
          {
            text: 'Нет чётких законодательных критериев',
            emphasis: 'Субъективность заключений',
          },
        ])}
      />
    );
    expect(container.querySelector('.block-list-item')?.textContent).toBe(
      'Субъективность заключений — Нет чётких законодательных критериев'
    );
  });
});
