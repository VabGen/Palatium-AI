import { describe, expect, it } from 'vitest';

import {
  ARTIFACT_MIN_PARAGRAPH_CHARS,
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

  it('accepts multi-block documents', () => {
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

  it('accepts documents with source citations', () => {
    expect(
      isArtifactWorthy(
        doc({
          meta: {
            confidence: 1,
            requires_review: false,
            source_refs: ['Договор.pdf'],
            interaction: 'none',
          },
        })
      )
    ).toBe(true);
  });
});

describe('artifactPreviewText', () => {
  it('returns the first paragraph truncated', () => {
    const long = 'Слово '.repeat(40).trim();
    const preview = artifactPreviewText(
      doc({ blocks: [{ type: 'paragraph', text: long }] }),
      40
    );
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
