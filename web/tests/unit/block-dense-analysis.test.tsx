import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import type { ContentDocument } from '../../src/types/contentDocument';

const denseAnalysisDoc = (): ContentDocument => ({
  schema_version: 1,
  locale: 'ru-RU',
  actions: [],
  blocks: [
    { type: 'heading', level: 2, text: 'Заказчик', icon: 'search' },
    {
      type: 'kv',
      items: [
        { label: 'Назначение', value: 'Поставка и внедрение СЭД' },
        { label: 'Срок', value: '10 рабочих дней' },
      ],
    },
    { type: 'heading', level: 2, text: 'Требования', icon: 'list' },
    {
      type: 'list',
      style: 'unordered',
      items: [
        { text: 'Функционал', level: 0 },
        { text: 'ЭЦП и маршруты', level: 1 },
        { text: 'Журнал аудита', level: 1 },
      ],
    },
    { type: 'heading', level: 2, text: 'Риски', icon: 'warning' },
    { type: 'callout', tone: 'warning', body: 'Срок сжатый относительно объёма работ.' },
  ],
  meta: { confidence: 0.9, requires_review: false, source_refs: [] },
});

describe('BlockRenderer dense analysis (Kimi parity)', () => {
  it('renders section headings, kv panel and nested list', () => {
    const { container } = render(<BlockRenderer document={denseAnalysisDoc()} />);

    expect(screen.getByText('Заказчик')).toBeInTheDocument();
    expect(screen.getByText('Назначение')).toBeInTheDocument();
    expect(screen.getByText('Поставка и внедрение СЭД')).toBeInTheDocument();
    expect(container.querySelectorAll('.block-heading').length).toBeGreaterThanOrEqual(2);
    expect(container.querySelector('.block-kv')).not.toBeNull();
    expect(container.querySelectorAll('.kv-row').length).toBe(2);
    expect(container.querySelector('li.nested')).not.toBeNull();
    expect(container.querySelectorAll('.token-icon').length).toBeGreaterThanOrEqual(2);
  });
});
