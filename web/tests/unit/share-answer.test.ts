import { afterEach, describe, expect, it, vi } from 'vitest';
import { shareAnswerText } from '../../src/lib/shareAnswer';

describe('shareAnswerText', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('uses Web Share API when available', async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', {
      share,
      canShare: () => true,
      clipboard: { writeText: vi.fn() },
    });
    await expect(shareAnswerText({ title: 'Answer', text: 'Hello' })).resolves.toBe('shared');
    expect(share).toHaveBeenCalledWith({ title: 'Answer', text: 'Hello' });
  });

  it('falls back to clipboard when share is unavailable', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', {
      clipboard: { writeText },
    });
    await expect(shareAnswerText({ title: 'Answer', text: 'Hello' })).resolves.toBe('copied');
    expect(writeText).toHaveBeenCalledWith('Hello');
  });

  it('returns failed for empty text', async () => {
    await expect(shareAnswerText({ title: 'Answer', text: '  ' })).resolves.toBe('failed');
  });
});
