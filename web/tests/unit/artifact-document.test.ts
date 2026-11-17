import { describe, expect, it } from 'vitest';

import {
  ARTIFACT_MIN_PARAGRAPH_CHARS,
  ARTIFACT_MIN_SUPPORT_CHARS,
  artifactPreviewText,
  isArtifactWorthy,
} from '../../src/lib/artifactDocument';
import type { ContentDocument } from '../../src/types/contentDocument';

function doc(overrides: Partial<ContentDocument> = {}): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks: [{ type: 'paragraph', text: 'Короткий ответ.' }],
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
      interaction: 'none',
    },
    ...overrides,
  };
}

describe('isArtifactWorthy', () => {
  it('rejects a short single paragraph (ack / format_only class)', () => {
    expect(isArtifactWorthy(doc())).toBe(false);
  });

  it('rejects short multi-paragraph social without dense payload', () => {
    expect(
      isArtifactWorthy(
        doc({
          blocks: [
            { type: 'paragraph', text: 'Привет! У меня всё отлично.' },
            { type: 'paragraph', text: 'А как ваши дела?' },
          ],
        })
      )
    ).toBe(false);
  });

  it('accepts dense kv even as a second block', () => {
    expect(
      isArtifactWorthy(
        doc({
          blocks: [
            { type: 'paragraph', text: 'Введение' },
            { type: 'kv', items: [{ label: 'Статус', value: 'Ок' }] },
          ],
        })
      )
    ).toBe(true);
  });

  it('accepts multi-section answers by heading count', () => {
    expect(
      isArtifactWorthy(
        doc({
          blocks: [
            { type: 'heading', level: 2, text: 'Шаг 1' },
            { type: 'paragraph', text: 'Бульон.' },
            { type: 'heading', level: 2, text: 'Шаг 2' },
            { type: 'paragraph', text: 'Зажарка.' },
          ],
        })
      )
    ).toBe(true);
  });

  it('accepts rich single blocks (table/list/code)', () => {
    expect(
      isArtifactWorthy(
        doc({
          blocks: [{ type: 'table', columns: ['A'], rows: [['1']] }],
        })
      )
    ).toBe(true);
  });

  it('accepts long single paragraphs by structural length threshold', () => {
    const text = 'а'.repeat(ARTIFACT_MIN_PARAGRAPH_CHARS);
    expect(isArtifactWorthy(doc({ blocks: [{ type: 'paragraph', text }] }))).toBe(true);
  });

  it('does not promote file Q&A to artifact just because source_refs exist', () => {
    // Citations are chips; «о чем файл» + short bullets must stay in the bubble.
    expect(
      isArtifactWorthy(
        doc({
          title: 'О чем файл',
          blocks: [
            {
              type: 'paragraph',
              text: 'Текст про рост цен на иван-чай из‑за высокого спроса.',
            },
            {
              type: 'list',
              style: 'unordered',
              items: [{ text: 'Розница: 3000–5000 ₽/кг' }, { text: 'Опт: 1500 ₽/кг' }],
            },
          ],
          meta: {
            confidence: 1,
            requires_review: false,
            source_refs: ['ht_1-5.webp'],
            interaction: 'none',
          },
        })
      )
    ).toBe(false);
  });

  it('ignores citations and HITL actions as sole artifact signals', () => {
    expect(
      isArtifactWorthy(
        doc({
          actions: [
            {
              action_id: 'a1',
              label: 'Вариант',
              kind: 'custom',
              style: 'secondary',
              requires_confirmation: false,
              risk_score: 0,
            },
          ],
          meta: {
            confidence: 1,
            requires_review: false,
            source_refs: ['Договор.pdf'],
            citations: [
              {
                source_ref: 'Договор.pdf',
                quote: 'п.1',
                anchor: 'url_only',
              },
            ],
            interaction: 'choice',
          },
        })
      )
    ).toBe(false);
  });

  it('accepts long list-shaped deliverables past the support mass threshold', () => {
    const item = 'а'.repeat(80);
    const items = Array.from({ length: 10 }, () => ({ text: item }));
    expect(items.reduce((n, row) => n + row.text.length, 0)).toBeGreaterThanOrEqual(
      ARTIFACT_MIN_SUPPORT_CHARS
    );
    expect(
      isArtifactWorthy(
        doc({
          blocks: [{ type: 'list', style: 'unordered', items }],
        })
      )
    ).toBe(true);
  });
});

describe('artifactPreviewText', () => {
  it('returns the first paragraph truncated', () => {
    const long = 'Слово '.repeat(40).trim();
    const preview = artifactPreviewText(doc({ blocks: [{ type: 'paragraph', text: long }] }), 40);
    expect(preview.endsWith('…')).toBe(true);
    expect(preview.length).toBeLessThanOrEqual(40);
  });

  it('falls back to title when blocks have no text', () => {
    expect(
      artifactPreviewText(
        doc({
          title: 'План работ',
          blocks: [{ type: 'divider' }],
        })
      )
    ).toBe('План работ');
  });
});
