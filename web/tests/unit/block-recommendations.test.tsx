import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BlockRenderer } from '../../src/components/BlockRenderer';
import { t } from '../../src/i18n';
import type { ContentDocument } from '../../src/types/contentDocument';

function docWith(blocks: ContentDocument['blocks']): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks,
    actions: [],
    meta: { confidence: 1, requires_review: false, source_refs: [], interaction: 'none' },
  };
}

describe('BlockRenderer recommendations card', () => {
  it('wraps a check-icon heading and following list in the cream tip card', () => {
    const { container } = render(
      <BlockRenderer
        document={docWith([
          { type: 'heading', level: 2, text: 'Рекомендации', icon: 'check' },
          {
            type: 'list',
            style: 'unordered',
            items: [
              { text: 'Уточнить предмет договора', emphasis: 'Уточнить предмет' },
              { text: 'Заполнить реквизиты' },
            ],
          },
        ])}
      />
    );

    const card = container.querySelector('.block-recommendations');
    expect(card).not.toBeNull();
    expect(screen.getByLabelText(t('doc.recommendations'))).toBe(card);
    expect(card?.querySelector('.block-recommendations__title')?.textContent).toBe(
      t('doc.recommendations')
    );
    expect(screen.queryByRole('heading', { name: 'Рекомендации' })).not.toBeInTheDocument();
    expect(screen.getByText(/Уточнить предмет договора/)).toBeInTheDocument();
  });

  it('does not skin a same-titled heading without check chrome', () => {
    const { container } = render(
      <BlockRenderer
        document={docWith([
          { type: 'heading', level: 2, text: 'Рекомендации' },
          { type: 'paragraph', text: 'Обычный абзац.' },
        ])}
      />
    );

    expect(container.querySelector('.block-recommendations')).toBeNull();
    expect(screen.getByRole('heading', { name: 'Рекомендации' })).toBeInTheDocument();
  });

  it('skins a check-icon callout as the same card', () => {
    const { container } = render(
      <BlockRenderer
        document={docWith([
          {
            type: 'callout',
            tone: 'success',
            icon: 'check',
            title: 'Recommendations',
            body: 'Check counterparty approval.',
          },
        ])}
      />
    );

    expect(container.querySelector('.block-recommendations')).not.toBeNull();
    expect(container.querySelector('.block-callout')).toBeNull();
    expect(screen.getByText('Check counterparty approval.')).toBeInTheDocument();
  });
});
