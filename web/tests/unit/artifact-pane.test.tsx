import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { ArtifactPane } from '../../src/components/ArtifactPane';
import { t } from '../../src/i18n';
import type { ContentDocument } from '../../src/types/contentDocument';

const document: ContentDocument = {
  schema_version: 1,
  locale: 'ru-RU',
  title: 'План по входящему №42',
  blocks: [
    { type: 'paragraph', text: 'Согласовать входящее и подготовить ответ.' },
    { type: 'kv', items: [{ label: 'Приоритет', value: 'Высокий' }] },
  ],
  actions: [],
  meta: {
    confidence: 0.9,
    requires_review: false,
    source_refs: [],
    interaction: 'none',
  },
};

describe('ArtifactPane', () => {
  it('renders title, body, and focuses the close control', () => {
    const onClose = vi.fn();
    render(
      <ArtifactPane
        document={document}
        messageId="msg-1"
        userId="u1"
        orgId="o1"
        busy={false}
        onClose={onClose}
        onLike={vi.fn()}
        onDislike={vi.fn()}
        onCopy={vi.fn()}
        onExportPdf={vi.fn()}
        onRegenerate={vi.fn()}
      />
    );

    expect(screen.getByRole('complementary', { name: t('artifact.paneLabel') })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'План по входящему №42' })).toBeTruthy();
    expect(screen.getByText('Согласовать входящее и подготовить ответ.')).toBeTruthy();

    const close = screen.getByRole('button', { name: t('artifact.close') });
    expect(close).toHaveFocus();
    fireEvent.click(close);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
