/**
 * Path C: stream preview and final BlockRenderer both use TokenIcon —
 * no raw ``<icon>`` tags, SVG present for the same token.
 */
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { BlockRenderer } from '../../src/components/BlockRenderer';
import { StreamMarkdownPreview } from '../../src/components/StreamMarkdownPreview';
import { sanitizeStreamMarkdown, stripIconTokens } from '../../src/lib/markdown';
import type { ContentDocument } from '../../src/types/contentDocument';

function docWithIcon(): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks: [{ type: 'heading', level: 2, text: 'Report', icon: 'document' }],
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
      interaction: 'none',
    },
  };
}

describe('icon render parity (preview ↔ final)', () => {
  it('preview and BlockRenderer both emit SVG, never raw icon tags', () => {
    const preview = render(
      <StreamMarkdownPreview markdown={'<icon name="document"/> Report'} />
    );
    const final = render(<BlockRenderer document={docWithIcon()} />);

    expect(preview.container.querySelector('svg')).not.toBeNull();
    expect(final.container.querySelector('svg')).not.toBeNull();
    expect(preview.container.textContent).not.toMatch(/<icon/);
    expect(final.container.textContent).not.toMatch(/<icon/);
    expect(preview.container.textContent).toMatch(/Report/);
    expect(final.container.textContent).toMatch(/Report/);
  });

  it('sanitize keeps icon as markdown image; strip removes both name= and x=', () => {
    const prepared = sanitizeStreamMarkdown('<icon x="check"/> Done');
    expect(prepared).toContain('palatium-icon:check');
    expect(prepared).not.toContain('<icon');
    expect(stripIconTokens('mid <icon name="check"/> text')).toBe('mid  text');
    expect(stripIconTokens('mid <icon x="check"/> text')).toBe('mid  text');
  });
});
