/**
 * kimi.ai parity: long multi-section answers render every H2 inline.
 * The chat view never folds answer sections into bordered `<details>` boxes.
 * Recommendation sections are the exception: cream tip card, not a collapsed details.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import { t } from '../../src/i18n';
import type { ContentBlock, ContentDocument } from '../../src/types/contentDocument';

function longAnalysisDoc(): ContentDocument {
  const blocks: ContentBlock[] = [
    { type: 'heading', level: 2, text: 'Введение' },
    { type: 'paragraph', text: 'Абзац 1.' },
    { type: 'heading', level: 2, text: 'Ключевые положения' },
    { type: 'paragraph', text: 'Абзац 2.' },
    { type: 'heading', level: 2, text: 'Риски' },
    { type: 'paragraph', text: 'Абзац 3.' },
    { type: 'heading', level: 2, text: 'Рекомендации', icon: 'check' },
    { type: 'paragraph', text: 'Абзац 4.' },
    { type: 'list', style: 'unordered', items: [{ text: 'пункт' }] },
  ];
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: 'Анализ',
    blocks,
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
      interaction: 'none',
    },
  };
}

describe('BlockRenderer section flow', () => {
  it('renders every section inline, with no collapsed boxes', () => {
    const { container } = render(<BlockRenderer document={longAnalysisDoc()} />);
    expect(container.querySelectorAll('details.doc-section.is-collapsible')).toHaveLength(0);
    const headings = [...container.querySelectorAll('.block-heading')].map(node =>
      node.textContent?.trim()
    );
    expect(headings).toEqual(expect.arrayContaining(['Введение', 'Ключевые положения', 'Риски']));
    expect(headings).not.toContain('Рекомендации');
    expect(container.querySelector('.block-recommendations')).not.toBeNull();
    expect(container.querySelector('.block-recommendations__title')?.textContent).toBe(
      t('doc.recommendations')
    );
  });
});
