/**
 * Место цитаты в источнике (W3b-2): окно текста, подсветка, честные отказы.
 *
 * Проверяется то, что нельзя заметить по коду:
 *  - подсветка ставится по АБСОЛЮТНЫМ смещениям сервера, пересчитанным в окно, и
 *    ровно на них — сдвиг на символ показывает не ту фразу;
 *  - «цитата встречается дважды» / «не найдена» — текст без подсветки и причина,
 *    а не подсветка ближайшего похожего места (055);
 *  - текст с редактированием помечен, иначе пользователь читает выдержку из
 *    отредактированного документа, считая её оригиналом;
 *  - ошибка даёт повтор, а не пустую панель.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { HttpResponse, http } from 'msw';
import { beforeEach, describe, expect, it } from 'vitest';

import { SourcePanel } from '../../src/components/SourcePanel';
import { t } from '../../src/i18n';
import type { CitationRef } from '../../src/types/contentDocument';
import { server } from '../msw';
import { setAuthToken, setRuntimeMode } from '../../src/runtime/auth';

const ATTACHMENT_ID = '11111111-2222-3333-4444-555555555555';
const LOCATE_URL = `*/api/attachments/${ATTACHMENT_ID}/citation-locate`;
const QUOTE = 'Оплата в течение 5 рабочих дней';
const WINDOW = `Договор поставки.\n\n2. Расчёт. ${QUOTE} с момента подписания.\n\n3. Прочее.`;

function citation(overrides: Partial<CitationRef> = {}): CitationRef {
  return {
    source_ref: 'Договор.pdf',
    source_id: ATTACHMENT_ID,
    anchor: 'char_location',
    quote: QUOTE,
    ...overrides,
  };
}

function response(overrides: Record<string, unknown> = {}) {
  const start = WINDOW.indexOf(QUOTE);
  return {
    attachment_id: ATTACHMENT_ID,
    filename: 'Договор.pdf',
    outcome: 'quote_match',
    start,
    end: start + QUOTE.length,
    window_start: 0,
    window_end: WINDOW.length,
    text: WINDOW,
    total_chars: WINDOW.length,
    text_state: 'full',
    ...overrides,
  };
}

function renderPanel(overrides: Partial<CitationRef> = {}) {
  return render(
    <SourcePanel
      citation={citation(overrides)}
      attachmentId={ATTACHMENT_ID}
      userId="user-1"
      orgId="org-1"
      onClose={() => {}}
    />
  );
}

beforeEach(() => {
  setRuntimeMode('standalone');
  setAuthToken('tok-1');
});

describe('SourcePanel', () => {
  it('highlights exactly the span the server located', async () => {
    server.use(http.post(LOCATE_URL, () => HttpResponse.json(response())));

    renderPanel();

    const mark = await screen.findByText(QUOTE);
    expect(mark.tagName).toBe('MARK');
  });

  it('maps absolute offsets into the returned window', async () => {
    // Окно начинается не с нуля: смещения сервера абсолютные, подсветка — локальная.
    const start = WINDOW.indexOf(QUOTE);
    const offset = 10;
    server.use(
      http.post(LOCATE_URL, () =>
        HttpResponse.json(
          response({
            window_start: offset,
            window_end: WINDOW.length,
            text: WINDOW.slice(offset),
            start,
            end: start + QUOTE.length,
          })
        )
      )
    );

    renderPanel();

    const mark = await screen.findByText(QUOTE);
    expect(mark.tagName).toBe('MARK');
  });

  it('says the quote is ambiguous instead of highlighting the first occurrence', async () => {
    server.use(
      http.post(LOCATE_URL, () =>
        HttpResponse.json(response({ outcome: 'ambiguous_quote', start: null, end: null }))
      )
    );

    renderPanel();

    expect(await screen.findByText(t('cite.sourceAmbiguous'))).toBeInTheDocument();
    expect(screen.queryByText(QUOTE)?.tagName).not.toBe('MARK');
  });

  it('says the quote was not found when the source disagrees', async () => {
    server.use(
      http.post(LOCATE_URL, () =>
        HttpResponse.json(response({ outcome: 'quote_not_found', start: null, end: null }))
      )
    );

    renderPanel();

    expect(await screen.findByText(t('cite.sourceNotFound'))).toBeInTheDocument();
  });

  it('says there is no extracted text rather than showing an empty panel', async () => {
    server.use(
      http.post(LOCATE_URL, () =>
        HttpResponse.json(
          response({
            outcome: 'no_text',
            start: null,
            end: null,
            window_start: 0,
            window_end: 0,
            text: '',
          })
        )
      )
    );

    renderPanel();

    expect(await screen.findByText(t('cite.sourceNoText'))).toBeInTheDocument();
  });

  it('marks a redacted body so it is never mistaken for the original', async () => {
    server.use(http.post(LOCATE_URL, () => HttpResponse.json(response({ text_state: 'masked' }))));

    renderPanel();

    expect(await screen.findByText(t('cite.sourceMasked'))).toBeInTheDocument();
  });

  it('offers a retry after a failure and re-requests the same quote', async () => {
    let calls = 0;
    server.use(
      http.post(LOCATE_URL, () => {
        calls += 1;
        // 404 не ретраится клиентом: проверяем обработку ошибки, а не backoff.
        return calls === 1
          ? HttpResponse.json({ detail: 'attachment not found' }, { status: 404 })
          : HttpResponse.json(response());
      })
    );

    renderPanel();

    expect(await screen.findByText(t('cite.sourceError'))).toBeInTheDocument();
    await fireEvent.click(screen.getByRole('button', { name: t('cite.sourceRetry') }));

    await waitFor(() => expect(screen.getByText(QUOTE).tagName).toBe('MARK'));
    expect(calls).toBe(2);
  });
});
