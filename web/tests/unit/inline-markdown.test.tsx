import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import { InlineMarkdown } from '../../src/components/InlineMarkdown';
import type { ContentDocument } from '../../src/types/contentDocument';

describe('InlineMarkdown', () => {
  it('renders bold and italic without visible asterisks', () => {
    render(<InlineMarkdown text="**Добавлено:** компонент *заказным*" />);
    expect(screen.getByText('Добавлено:')).toBeInTheDocument();
    expect(screen.getByText('заказным')).toBeInTheDocument();
    expect(screen.queryByText(/\*\*/)).toBeNull();
    expect(screen.getByText('Добавлено:').tagName).toBe('STRONG');
    expect(screen.getByText('заказным').tagName).toBe('EM');
  });
});

describe('BlockRenderer table cells', () => {
  it('does not show raw markdown markers in table cells', () => {
    const doc: ContentDocument = {
      schema_version: 1,
      locale: 'ru',
      blocks: [
        {
          type: 'table',
          columns: ['Пункт', 'Суть отличия'],
          rows: [['**6.2**', '**Защита от споров.** В Скан 1 статус *заказного*.']],
        },
      ],
      actions: [],
      meta: {
        confidence: 0.9,
        requires_review: false,
        source_refs: [],
      },
    };
    render(<BlockRenderer document={doc} />);
    expect(screen.getByText('6.2')).toBeInTheDocument();
    expect(screen.getByText('Защита от споров.')).toBeInTheDocument();
    expect(screen.getByText('заказного')).toBeInTheDocument();
    expect(screen.queryByText(/\*\*6\.2\*\*/)).toBeNull();
    expect(screen.queryByText(/\*\*Защита/)).toBeNull();
  });
});
