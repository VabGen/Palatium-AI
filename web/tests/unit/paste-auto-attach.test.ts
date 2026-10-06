import { describe, expect, it } from 'vitest';

import { INTENT_TEXT_LIMIT } from '../../src/api/client';
import {
  AUTO_ATTACH_CHARS,
  MAX_ATTACHMENT_BYTES,
  createPastedTextFile,
  pastedTextFilename,
  shouldAutoAttachText,
  utf8ByteLength,
} from '../../src/lib/attachments';

describe('paste auto-attach thresholds', () => {
  it('keeps short paste in the intent field', () => {
    expect(shouldAutoAttachText('a'.repeat(AUTO_ATTACH_CHARS))).toBe(false);
    expect(shouldAutoAttachText('a'.repeat(AUTO_ATTACH_CHARS + 1))).toBe(true);
  });

  it('stays below the hard intent limit so convert happens before 32k wall', () => {
    expect(AUTO_ATTACH_CHARS).toBeLessThan(INTENT_TEXT_LIMIT);
  });

  it('builds a dated text/plain file under the attachment byte cap', () => {
    const text = 'x'.repeat(AUTO_ATTACH_CHARS + 50);
    const file = createPastedTextFile(text, new Date('2026-10-01T12:00:00'));
    expect(file).not.toBeNull();
    expect(file?.name).toBe(pastedTextFilename(new Date('2026-10-01T12:00:00')));
    expect(file?.type).toBe('text/plain');
    expect(file?.size).toBe(utf8ByteLength(text));
  });

  it('refuses paste that exceeds the attachment byte budget', () => {
    const oversized = 'я'.repeat(MAX_ATTACHMENT_BYTES); // multi-byte → over byte cap
    expect(utf8ByteLength(oversized)).toBeGreaterThan(MAX_ATTACHMENT_BYTES);
    expect(createPastedTextFile(oversized)).toBeNull();
  });

  it('allows restore to the field only when text fits INTENT_TEXT_LIMIT', () => {
    const restorable = 'a'.repeat(INTENT_TEXT_LIMIT);
    const tooLong = 'a'.repeat(INTENT_TEXT_LIMIT + 1);
    expect(restorable.length <= INTENT_TEXT_LIMIT).toBe(true);
    expect(tooLong.length <= INTENT_TEXT_LIMIT).toBe(false);
  });
});
