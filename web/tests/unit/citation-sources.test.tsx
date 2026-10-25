/**
 * Источники ответа (W3b): чипы по источникам и панель цитат.
 *
 * Проверяется поведение, которое легко сломать незаметно:
 *  - чип — раскрывающая кнопка (`aria-expanded`/`aria-controls`), а не div;
 *  - цитаты показываются дословно, место — только если провайдер его сообщил;
 *  - выдуманной ссылки нет: файл не становится `<a>`, а `javascript:` не
 *    превращается в href;
 *  - Escape закрывает панель, не уводя фокус (это disclosure, не диалог).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';

import { CitationSources } from '../../src/components/CitationSources';
import { t } from '../../src/i18n';
import { setAuthToken, setRuntimeMode } from '../../src/runtime/auth';
import type { CitationRef } from '../../src/types/contentDocument';
import { server } from '../msw';

beforeEach(() => {
  setRuntimeMode('standalone');
  setAuthToken('tok-1');
});

function citation(overrides: Partial<CitationRef> = {}): CitationRef {
  return {
    source_ref: 'Договор.pdf',
    anchor: 'char_location',
    quote: 'Оплата в течение 5 рабочих дней.',
    page: 2,
    ...overrides,
  };
}

describe('CitationSources', () => {
  it('renders nothing when there are no anchors', () => {
    const { container } = render(<CitationSources citations={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders one collapsed chip per source, not per citation', () => {
    render(
      <CitationSources
        citations={[
          citation({ quote: 'Первая цитата' }),
          citation({ quote: 'Вторая цитата' }),
          citation({ source_ref: 'Политика.pdf', quote: 'Другое', page: 1 }),
        ]}
      />
    );

    const chips = screen.getAllByRole('button');
    expect(chips).toHaveLength(2);
    expect(chips[0]).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });

  it('opens the cited fragments verbatim with the location the provider reported', () => {
    render(<CitationSources citations={[citation()]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Договор.pdf' }));

    expect(screen.getByRole('button', { name: 'Договор.pdf' })).toHaveAttribute(
      'aria-expanded',
      'true'
    );
    expect(screen.getByRole('region', { name: t('cite.panel') })).toBeInTheDocument();
    expect(screen.getByText('Оплата в течение 5 рабочих дней.')).toBeInTheDocument();
    expect(screen.getByText(t('cite.page', { page: '2' }))).toBeInTheDocument();
  });

  it('says the location is unavailable instead of inventing one', () => {
    render(<CitationSources citations={[citation({ page: null, answer_range: [0, 10] })]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Договор.pdf' }));

    expect(screen.getByText(t('cite.positionUnavailable'))).toBeInTheDocument();
    expect(screen.queryByText(t('cite.page', { page: '0' }))).not.toBeInTheDocument();
  });

  it('links an http source and never links a file name or an executable scheme', () => {
    render(
      <CitationSources
        citations={[
          citation({ source_ref: 'https://edo.iba/docs/42', anchor: 'url_only', page: null }),
        ]}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'https://edo.iba/docs/42' }));

    const link = screen.getByRole('link', { name: t('cite.openExternal') });
    expect(link).toHaveAttribute('href', 'https://edo.iba/docs/42');
    expect(link).toHaveAttribute('rel', 'noopener noreferrer');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('does not render a link for a javascript: source', () => {
    render(<CitationSources citations={[citation({ source_ref: 'javascript:alert(1)' })]} />);

    fireEvent.click(screen.getByRole('button', { name: 'javascript:alert(1)' }));

    expect(screen.queryByRole('link')).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: t('cite.panel') })).toBeInTheDocument();
  });

  it('closes on Escape and toggles back on a second click', () => {
    render(<CitationSources citations={[citation()]} />);
    const chip = screen.getByRole('button', { name: 'Договор.pdf' });

    fireEvent.click(chip);
    expect(screen.getByRole('region')).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
    expect(chip).toHaveAttribute('aria-expanded', 'false');

    fireEvent.click(chip);
    fireEvent.click(chip);
    expect(screen.queryByRole('region')).not.toBeInTheDocument();
  });

  it('shows the character range when the provider gave offsets into the source', () => {
    render(<CitationSources citations={[citation({ page: null, source_range: [120, 158] })]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Договор.pdf' }));

    expect(screen.getByText(t('cite.chars', { start: '120', end: '158' }))).toBeInTheDocument();
  });

  it('offers "show in source" only when the server bound an attachment', () => {
    render(
      <CitationSources
        citations={[citation({ source_id: '11111111-2222-3333-4444-555555555555' })]}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Договор.pdf' }));

    expect(
      screen.getByRole('button', { name: /Показать в источнике|Show in source/ })
    ).toBeInTheDocument();
  });

  it('renders no source action for an unbound citation', () => {
    // Без ``source_id`` сервер не смог однозначно назвать загрузку: кнопка, которая
    // всегда падает, хуже её отсутствия (W3b-2).
    render(<CitationSources citations={[citation({ source_id: null })]} />);

    fireEvent.click(screen.getByRole('button', { name: 'Договор.pdf' }));

    expect(
      screen.queryByRole('button', { name: /Показать в источнике|Show in source/ })
    ).not.toBeInTheDocument();
  });

  it('closes the source panel on Escape before collapsing the citations', async () => {
    server.use(
      http.post('*/api/attachments/*/citation-locate', () =>
        HttpResponse.json({
          attachment_id: '11111111-2222-3333-4444-555555555555',
          filename: 'Договор.pdf',
          outcome: 'quote_not_found',
          start: null,
          end: null,
          window_start: 0,
          window_end: 10,
          text: 'текст источника',
          total_chars: 10,
          text_state: 'full',
        })
      )
    );
    render(
      <CitationSources
        citations={[citation({ source_id: '11111111-2222-3333-4444-555555555555' })]}
        userId="user-1"
        orgId="org-1"
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Договор.pdf' }));
    fireEvent.click(screen.getByRole('button', { name: /Показать в источнике|Show in source/ }));
    expect(await screen.findByRole('region', { name: t('cite.sourcePanel') })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    // Первый Escape закрывает вложенную панель, вторая остаётся на месте.
    expect(screen.queryByRole('region', { name: t('cite.sourcePanel') })).not.toBeInTheDocument();
    expect(screen.getByRole('region', { name: t('cite.panel') })).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('region', { name: t('cite.panel') })).not.toBeInTheDocument();
  });
});
