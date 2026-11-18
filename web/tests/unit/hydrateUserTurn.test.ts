import { afterEach, describe, expect, it, vi } from 'vitest';
import { hydrateUserTurn } from '../../src/lib/hydrateUserTurn';

vi.mock('../../src/api/client', () => ({
  fetchAttachment: vi.fn(async (id: string) => ({
    attachment_id: id,
    thread_id: 'th-1',
    filename: id === 'aid-1' ? 'Договор.docx' : `file-${id}.pdf`,
    mime_type: 'application/octet-stream',
    size_bytes: 10,
    mode: 'attach',
    status: 'ready',
    page_count: null,
    rejection_reason: null,
    error: null,
    created_at: '2026-01-01T00:00:00Z',
    expires_at: null,
  })),
}));

import { fetchAttachment } from '../../src/api/client';

afterEach(() => {
  vi.mocked(fetchAttachment).mockClear();
});

describe('hydrateUserTurn', () => {
  it('restores attachment names from payload without fetching', async () => {
    const hydrated = await hydrateUserTurn(
      'сравни файлы',
      {
        attachment_ids: ['aid-1', 'aid-2'],
        attachment_names: ['Договор.docx', 'Договор_2.docx'],
      },
      'u1',
      'o1'
    );
    expect(hydrated).toEqual({
      text: 'сравни файлы',
      attachmentIds: ['aid-1', 'aid-2'],
      attachmentNames: ['Договор.docx', 'Договор_2.docx'],
    });
    expect(fetchAttachment).not.toHaveBeenCalled();
  });

  it('fetches filenames when only attachment_ids are stored', async () => {
    const hydrated = await hydrateUserTurn(
      'о чем файл',
      { attachment_ids: ['aid-1'] },
      'u1',
      'o1'
    );
    expect(hydrated.attachmentIds).toEqual(['aid-1']);
    expect(hydrated.attachmentNames).toEqual(['Договор.docx']);
    expect(fetchAttachment).toHaveBeenCalledWith('aid-1', 'u1', 'o1');
  });

  it('rewrites HITL resume envelopes to the human label', async () => {
    const envelope =
      '<<<HITL_CHOICE_RESUME kind=clarify action_id=filesel_1 option_kind=custom>>>\n' +
      '<<<UNTRUSTED_HITL_LABEL\nДоговор оказания услуг.docx\n<<<END_UNTRUSTED_HITL_LABEL>>>';
    const hydrated = await hydrateUserTurn(envelope, null);
    expect(hydrated.text).toBe('Договор оказания услуг.docx');
    expect(hydrated.attachmentIds).toEqual([]);
  });
});
