import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StreamMarkdownPreview } from '../../src/components/StreamMarkdownPreview';
import { closeDanglingMarkdown, sanitizeStreamMarkdown } from '../../src/lib/markdown';

describe('closeDanglingMarkdown', () => {
  it('is idempotent on complete markdown', () => {
    const md = '### Title\n\n- a\n- b\n';
    expect(closeDanglingMarkdown(md)).toBe(md);
  });

  it('closes an open fence without breaking later render', () => {
    const open = '```ts\nconst x = 1';
    const closed = closeDanglingMarkdown(open);
    expect(closed.endsWith('```')).toBe(true);
  });
});

describe('StreamMarkdownPreview', () => {
  it('renders a heading from ###, not a literal hash prefix', () => {
    render(<StreamMarkdownPreview markdown="### Заголовок" />);
    const heading = screen.getByRole('heading', { level: 3 });
    expect(heading).toHaveTextContent('Заголовок');
    expect(screen.queryByText(/###/)).toBeNull();
  });

  it('strips icon tokens and emoji from preview', () => {
    render(
      <StreamMarkdownPreview markdown={'<icon name="document"/> Note 📄'} />
    );
    expect(screen.getByText(/Note/)).toBeInTheDocument();
    expect(screen.queryByText(/icon/)).toBeNull();
    expect(screen.queryByText(/📄/)).toBeNull();
  });

  it('sanitizeStreamMarkdown closes dangling bold', () => {
    expect(sanitizeStreamMarkdown('**bold')).toContain('**bold**');
  });
});
