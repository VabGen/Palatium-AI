import { describe, expect, it } from 'vitest';
import { stripHitlTags } from '../../src/lib/stripHitlTags';
import { sanitizeStreamMarkdown } from '../../src/lib/markdown';

describe('stripHitlTags', () => {
  it('removes hitl-action and hitl-choice tags', () => {
    const md =
      'Ready.\n\n<hitl-action kind="confirm" label="Go" />\n<hitl-choice options=\'["A","B"]\' />\n';
    expect(stripHitlTags(md)).toBe('Ready.');
  });
});

describe('sanitizeStreamMarkdown', () => {
  it('removes hitl tags for preview', () => {
    const md = 'Ready.\n\n<hitl-action kind="confirm" label="Go" />\n';
    expect(sanitizeStreamMarkdown(md)).toBe('Ready.');
  });
});
