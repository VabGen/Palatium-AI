/**
 * Long multi-section answers collapse tail H2 sections (progressive disclosure).
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import type { ContentBlock, ContentDocument } from '../../src/types/contentDocument';

function longAnalysisDoc(): ContentDocument {
  const blocks: ContentBlock[] = [
    { type: 'heading', level: 2, text: 'Введение' },
    { type: 'paragraph', text: 'Абзац 1.' },
    { type: 'heading', level: 2, text: 'Ключевые положения' },
    { type: 'paragraph', text: 'Абзац 2.' },
    { type: 'heading', level: 2, text: 'Риски' },
    { type: 'paragraph', text: 'Абзац 3.' },
    { type: 'heading', level: 2, text: 'Рекомендации' },
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

describe('BlockRenderer section collapse', () => {
  it('collapses sections after the first two when the document is long', () => {
    const { container } = render(<BlockRenderer document={longAnalysisDoc()} />);
    const collapsible = container.querySelectorAll('details.doc-section.is-collapsible');
    expect(collapsible.length).toBeGreaterThanOrEqual(1);
    expect(collapsible[0].querySelector('summary')?.textContent).toContain('Риски');
  });
});
