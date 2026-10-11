import { describe, expect, it } from 'vitest';

import { previewTextFromFormatterJson } from '../../src/api/client';
import { closeIncompleteMarkdown } from '../../src/lib/incompleteMarkdown';

describe('previewTextFromFormatterJson', () => {
  it('extracts paragraph text fields from partial formatter JSON', () => {
    const partial =
      '{"schema_version":1,"locale":"ru","blocks":[{"type":"paragraph","text":"Привет"},';
    expect(previewTextFromFormatterJson(partial)).toBe('Привет');
  });

  it('joins multiple text fields', () => {
    const payload =
      '{"blocks":[{"type":"paragraph","text":"One"},{"type":"paragraph","text":"Two"}]}';
    expect(previewTextFromFormatterJson(payload)).toBe('One\n\nTwo');
  });

  it('returns empty when no text fields yet', () => {
    expect(previewTextFromFormatterJson('{"schema_version":1')).toBe('');
  });

  it('pending path closes incomplete markdown after JSON extract', () => {
    const partial =
      '{"blocks":[{"type":"paragraph","text":"Hello **world"}]}';
    const preview = previewTextFromFormatterJson(partial);
    expect(closeIncompleteMarkdown(preview)).toBe('Hello **world**');
  });
});
