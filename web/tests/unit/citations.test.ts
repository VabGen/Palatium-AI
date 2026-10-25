/**
 * Цитаты → модель для UI (W3b): группировка, дедупликация, безопасные ссылки.
 *
 * Ключевое, что защищается тестами:
 *  - две цитаты одного источника — один чип, а не два;
 *  - `answer_range` никогда не выдаётся за позицию В ИСТОЧНИКЕ;
 *  - `javascript:`/`data:` из ответа модели не становятся `href` (020);
 *  - «провайдер не сообщил» — это `none`, а не нулевая позиция.
 */
import { describe, expect, it } from 'vitest';

import {
  citationKey,
  citationPosition,
  groupCitations,
  safeSourceHref,
} from '../../src/lib/citations';
import type { CitationRef } from '../../src/types/contentDocument';

function citation(overrides: Partial<CitationRef> = {}): CitationRef {
  return { source_ref: 'Договор.pdf', anchor: 'char_location', ...overrides };
}

describe('safeSourceHref', () => {
  it('keeps absolute http(s) sources', () => {
    expect(safeSourceHref('https://edo.iba/docs/42')).toBe('https://edo.iba/docs/42');
    expect(safeSourceHref('http://example.test/a?b=1')).toBe('http://example.test/a?b=1');
  });

  it('treats a filename as a name, not a link', () => {
    expect(safeSourceHref('Договор.pdf')).toBeNull();
    expect(safeSourceHref('www.example.test')).toBeNull();
  });

  it('rejects executable and inline schemes', () => {
    expect(safeSourceHref('javascript:alert(1)')).toBeNull();
    expect(safeSourceHref('JavaScript:alert(1)')).toBeNull();
    expect(safeSourceHref('data:text/html,<script>alert(1)</script>')).toBeNull();
    expect(safeSourceHref('  ')).toBeNull();
  });
});

describe('citationPosition', () => {
  it('prefers the page the provider reported', () => {
    expect(citationPosition(citation({ page: 3, source_range: [0, 10] }))).toEqual({
      kind: 'page',
      page: 3,
    });
  });

  it('falls back to the source character range', () => {
    expect(citationPosition(citation({ source_range: [12, 30] }))).toEqual({
      kind: 'chars',
      start: 12,
      end: 30,
    });
  });

  it('never turns an answer offset into a source position', () => {
    expect(citationPosition(citation({ answer_range: [0, 5] }))).toEqual({ kind: 'none' });
  });

  it('reports an unknown position as unknown, not as zero', () => {
    expect(citationPosition(citation())).toEqual({ kind: 'none' });
    expect(citationPosition(citation({ page: 0 }))).toEqual({ kind: 'none' });
    expect(citationPosition(citation({ source_range: [7, 7] }))).toEqual({ kind: 'none' });
  });
});

describe('groupCitations', () => {
  it('groups by source and keeps document order', () => {
    const groups = groupCitations([
      citation({ quote: 'Первый фрагмент' }),
      citation({ source_ref: 'Политика.pdf', quote: 'Другой источник' }),
      citation({ quote: 'Второй фрагмент' }),
    ]);

    expect(groups.map(group => group.sourceRef)).toEqual(['Договор.pdf', 'Политика.pdf']);
    expect(groups[0]?.citations).toHaveLength(2);
    expect(groups[0]?.citations.map(item => item.quote)).toEqual([
      'Первый фрагмент',
      'Второй фрагмент',
    ]);
  });

  it('drops exact duplicates without merging different quotes', () => {
    const groups = groupCitations([
      citation({ quote: 'Одна и та же цитата' }),
      citation({ quote: 'Одна и та же цитата' }),
      citation({ quote: 'Одна и та же цитата', page: 4 }),
    ]);

    expect(groups).toHaveLength(1);
    expect(groups[0]?.citations).toHaveLength(2);
  });

  it('exposes an href only for URL sources', () => {
    const [file, url] = groupCitations([
      citation({ source_ref: 'Договор.pdf' }),
      citation({ source_ref: 'https://edo.iba/docs/42', anchor: 'url_only' }),
    ]);

    expect(file?.href).toBeNull();
    expect(url?.href).toBe('https://edo.iba/docs/42');
  });

  it('returns nothing for an empty list', () => {
    expect(groupCitations([])).toEqual([]);
  });
});

describe('citationKey', () => {
  it('distinguishes anchors that differ in any addressable part', () => {
    const base = citation({ quote: 'Текст', page: 2 });
    expect(citationKey(base)).toBe(citationKey(citation({ quote: 'Текст', page: 2 })));
    expect(citationKey(base)).not.toBe(citationKey(citation({ quote: 'Текст', page: 3 })));
    expect(citationKey(base)).not.toBe(citationKey(citation({ quote: 'Другое', page: 2 })));
    expect(citationKey(base)).not.toBe(
      citationKey(citation({ quote: 'Текст', page: 2, anchor: 'page_location' }))
    );
  });
});
