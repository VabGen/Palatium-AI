import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ProductShowcase } from '../../src/components/ProductShowcase';
import { setI18nLocale } from '../../src/i18n';

beforeEach(() => {
  setI18nLocale('en-US');
});

afterEach(() => {
  setI18nLocale('ru-RU');
});

describe('Product showcase shelf', () => {
  it('renders the docs shelf with kimi.ai section heading and cards', () => {
    const { container } = render(<ProductShowcase view="docs" />);

    expect(container.querySelector('.product-showcase')).not.toBeNull();
    expect(screen.getByText('Featured document examples')).toBeTruthy();
    expect(container.querySelectorAll('.product-showcase__caption')).toHaveLength(3);
    expect(screen.getByText('Tesla tear sheet')).toBeTruthy();
  });

  it('renders nothing for a view without a shelf', () => {
    const { container } = render(<ProductShowcase view="plugins" />);
    expect(container.querySelector('.product-showcase')).toBeNull();
  });

  it('keeps the first pill as the full shelf and filters the rest', () => {
    const { container } = render(<ProductShowcase view="slides" />);

    expect(container.querySelectorAll('.product-showcase__caption')).toHaveLength(6);

    fireEvent.click(screen.getByRole('tab', { name: 'Finance' }));

    const captions = [...container.querySelectorAll('.product-showcase__caption')].map(node =>
      node.textContent?.trim()
    );
    expect(captions).toEqual(['Series A Pitch Deck', 'Quarterly Business Review']);
    expect(screen.getByRole('tab', { name: 'Finance' }).getAttribute('aria-selected')).toBe('true');
  });

  it('reorders the shelf on shuffle', () => {
    const { container } = render(<ProductShowcase view="sheets" />);
    const read = () =>
      [...container.querySelectorAll('.product-showcase__caption')].map(node =>
        node.textContent?.trim()
      );

    const before = read();
    fireEvent.click(screen.getByRole('button', { name: 'Shuffle' }));
    const after = read();

    expect(after).toHaveLength(before.length);
    expect(after).not.toEqual(before);
    expect(new Set(after)).toEqual(new Set(before));
  });

  it('inserts the example prompt into chat without opening a detail sheet', () => {
    const onSelectPrompt = vi.fn();
    render(<ProductShowcase view="docs" onSelectPrompt={onSelectPrompt} />);

    fireEvent.click(screen.getByRole('button', { name: 'Insert into chat: Tesla tear sheet' }));

    expect(onSelectPrompt).toHaveBeenCalledTimes(1);
    expect(onSelectPrompt.mock.calls[0]?.[0]).toContain('Tesla tear sheet');
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('inserts masonry card prompts without a detail overlay', () => {
    const onSelectPrompt = vi.fn();
    render(<ProductShowcase view="make3d" onSelectPrompt={onSelectPrompt} />);

    fireEvent.click(screen.getByRole('button', { name: 'Insert into chat: Cologne Cathedral' }));

    expect(onSelectPrompt).toHaveBeenCalledTimes(1);
    expect(onSelectPrompt.mock.calls[0]?.[0]).toContain('Cologne Cathedral');
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
