import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { WidgetEmbed } from '../../src/components/WidgetEmbed';
import type { WidgetBlock } from '../../src/types/contentDocument';

/**
 * Компонентный слой (084): React Testing Library + jsdom.
 *
 * Взят именно `WidgetEmbed`, потому что это единственный блок, который рендерит
 * ССЫЛКУ из ответа модели: `href` приходит из недоверенного текста, и правило
 * «только http/https» — это защита, а не оформление. E2E его не проверяет: там нет
 * фикстуры с `javascript:`-ссылкой, и добавление её в общий стенд стоило бы дороже.
 */

function block(overrides: Partial<WidgetBlock> = {}): WidgetBlock {
  return { type: 'widget', kind: 'document', ref_id: 'DOC-1', ...overrides };
}

describe('WidgetEmbed', () => {
  it('uses the block title as the label when the host sent one', () => {
    const { container } = render(<WidgetEmbed block={block({ title: 'Договор №1' })} />);

    expect(container.querySelector('strong')).toHaveTextContent('Договор №1');
  });

  it('falls back to the reference id when there is no title', () => {
    // Именно `strong` — заголовок блока: `ref_id` рендерится ещё и подписью ниже,
    // поэтому поиск по всему документу нашёл бы два совпадения.
    const { container } = render(<WidgetEmbed block={block()} />);

    expect(container.querySelector('strong')).toHaveTextContent('DOC-1');
  });

  it.each([
    ['an absolute http link', 'http://edo.example/doc/1'],
    ['an absolute https link', 'https://edo.example/doc/1'],
  ])('renders a call-to-action for %s', (_label, href) => {
    render(<WidgetEmbed block={block({ href })} />);

    const link = screen.getByRole('link', { name: 'Open' });

    expect(link).toHaveAttribute('href', href);
    // rel обязателен вместе с target=_blank: без него открытая страница получает
    // доступ к window.opener (tabs nabbing / reverse tabnabbing).
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it.each([
    ['a javascript: URL', 'javascript:alert(1)'],
    ['a data: URL', 'data:text/html,<script>alert(1)</script>'],
    ['a vbscript: URL', 'vbscript:msgbox(1)'],
    ['a scheme-less value', 'edo.example/doc/1'],
  ])('renders no link at all for %s', (_label, href) => {
    render(<WidgetEmbed block={block({ href })} />);

    // Отклоняем не текст, а саму возможность клика: ссылка не появляется в DOM.
    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });

  it('treats a blank href as «no link» instead of rendering an empty anchor', () => {
    render(<WidgetEmbed block={block({ href: '   ' })} />);

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
  });
});
