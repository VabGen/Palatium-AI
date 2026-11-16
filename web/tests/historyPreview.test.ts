import { describe, expect, it } from 'vitest';
import { cleanHistorySnippet, extractHistoryPreview } from '../src/lib/historyPreview';

describe('cleanHistorySnippet', () => {
  it('strips markdown noise and clamps length', () => {
    const raw = '# Heading\n\n**Bold** claim about [link](https://x.test) and more words.';
    expect(cleanHistorySnippet(raw, 40)).toBe('Heading Bold claim about link and more…');
  });

  it('returns null for empty input', () => {
    expect(cleanHistorySnippet('   ')).toBeNull();
  });
});

describe('extractHistoryPreview', () => {
  it('takes the last assistant snippet and unique source refs', () => {
    const preview = extractHistoryPreview([
      {
        thread_id: 't1',
        role: 'user',
        content: 'compare files',
        seq: 1,
        payload: { attachment_names: ['a.pdf'] },
      },
      {
        thread_id: 't1',
        role: 'assistant',
        content: 'First answer',
        seq: 2,
        payload: { meta: { source_refs: ['a.pdf', 'b.xlsx'] } },
      },
      {
        thread_id: 't1',
        role: 'assistant',
        content: '## Final\n\nDetailed comparison of the scans.',
        seq: 3,
        payload: { meta: { source_refs: ['b.xlsx', 'c.pdf'] } },
      },
    ]);

    expect(preview.snippet).toBe('Final Detailed comparison of the scans.');
    expect(preview.files.map(file => file.filename)).toEqual(['a.pdf', 'b.xlsx', 'c.pdf']);
    expect(preview.files[1]?.meta).toBe('XLSX');
  });

  it('formats EXT + size when attachments carry size_bytes', () => {
    const preview = extractHistoryPreview([
      {
        thread_id: 't1',
        role: 'user',
        content: 'files',
        seq: 1,
        payload: {
          attachment_names: ['табл2026.xlsx'],
          attachments: [{ filename: 'табл2026.xlsx', size_bytes: 7967 }],
        },
      },
    ]);

    expect(preview.files).toHaveLength(1);
    expect(preview.files[0]?.meta).toMatch(/^XLSX /);
  });

  it('drops from-memory provenance stamp from history file chips', () => {
    const preview = extractHistoryPreview([
      {
        thread_id: 't1',
        role: 'assistant',
        content: 'Recall answer',
        seq: 1,
        payload: { meta: { source_refs: ['Обращение.docx', 'from memory'] } },
      },
    ]);

    expect(preview.files.map(file => file.filename)).toEqual(['Обращение.docx']);
  });
});
