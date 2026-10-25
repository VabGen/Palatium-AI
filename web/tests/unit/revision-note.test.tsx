/**
 * Доработка ответа (W7b): заметка о diff'е и разметка изменённых блоков.
 *
 * Что здесь зафиксировано, потому что ломается молча:
 *  - разметка ставится ТОЛЬКО по индексам сервера — клиент не считает content-hash;
 *  - старый payload без `changed_block_indices` показывает счётчики, но не красит
 *    блоки (подсветка «примерно» указала бы не туда);
 *  - `removed_blocks` — только число: удалённого блока в документе уже нет;
 *  - индексы адресуют `document.blocks`, поэтому список берётся из того же документа,
 *    что отрисован, а не из ревизии.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { BlockRenderer } from '../../src/components/BlockRenderer';
import { RevisionNote } from '../../src/components/RevisionNote';
import { t } from '../../src/i18n';
import type { ContentDocument, DocumentRevision } from '../../src/types/contentDocument';

function doc(...texts: string[]): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: null,
    blocks: texts.map(text => ({ type: 'paragraph', text })),
    actions: [],
    meta: { confidence: 0.9, requires_review: false, source_refs: [] },
  };
}

function revision(overrides: Partial<DocumentRevision> = {}): DocumentRevision {
  return {
    revision_of: 'prev-hash',
    changed_blocks: ['b1'],
    changed_block_indices: [1],
    removed_blocks: [],
    unchanged_blocks: 1,
    ...overrides,
  };
}

describe('RevisionNote', () => {
  it('renders nothing without a revision', () => {
    const { container } = render(<RevisionNote revision={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('states how many blocks changed and how many were removed', () => {
    render(<RevisionNote revision={revision({ removed_blocks: ['gone'] })} />);

    expect(screen.getByRole('note')).toHaveTextContent(t('revision.title'));
    expect(screen.getByRole('note')).toHaveTextContent(t('revision.changedCount', { count: 1 }));
    expect(screen.getByRole('note')).toHaveTextContent(t('revision.removedCount', { count: 1 }));
  });

  it('keeps a diff with only removals, and hides one with no changes', () => {
    const { rerender } = render(
      <RevisionNote revision={revision({ changed_blocks: [], removed_blocks: ['gone'] })} />
    );
    expect(screen.getByRole('note')).toHaveTextContent(t('revision.removedCount', { count: 1 }));

    rerender(<RevisionNote revision={revision({ changed_blocks: [], removed_blocks: [] })} />);
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
  });
});

describe('BlockRenderer revision marks', () => {
  it('marks only the blocks the server pointed at', () => {
    const { container } = render(
      <BlockRenderer document={doc('Первое.', 'Второе.', 'Третье.')} revision={revision()} />
    );

    const marked = container.querySelectorAll('[data-revision="changed"]');
    expect(marked).toHaveLength(1);
    expect(marked[0]).toHaveTextContent('Второе.');
    expect(marked[0]).toHaveTextContent(t('revision.changedBlock'));
  });

  it('never marks anything without a revision', () => {
    const { container } = render(<BlockRenderer document={doc('Первое.', 'Второе.')} />);
    expect(container.querySelector('[data-revision]')).toBeNull();
  });

  it('shows no marks for a legacy revision that carried no indices', () => {
    const legacy = revision();
    delete legacy.changed_block_indices;
    const { container } = render(
      <BlockRenderer document={doc('Первое.', 'Второе.')} revision={legacy} />
    );

    expect(container.querySelector('[data-revision]')).toBeNull();
  });

  it('ignores an index that no longer exists in the document', () => {
    const { container } = render(
      <BlockRenderer
        document={doc('Первое.')}
        revision={revision({ changed_block_indices: [7] })}
      />
    );

    expect(container.querySelector('[data-revision]')).toBeNull();
  });
});
