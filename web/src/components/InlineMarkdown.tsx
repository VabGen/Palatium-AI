import { memo } from 'react';
import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type Props = {
  text: string;
};

/**
 * Inline GFM subset for ContentDocument string fields.
 * Formatter streams ``**bold**`` / ``*italic*``; BlockRenderer must not show markers.
 * Block constructs (tables, lists, headings) are disallowed — structure already
 * lives in typed blocks; cells stay inline-only.
 */
const inlineComponents: Components = {
  // Cell/paragraph fields are already wrapped by the host element.
  p: ({ children }) => <>{children}</>,
  // Never promote stream/doc links to navigation (020 / host boundary).
  a: ({ children }) => <span>{children}</span>,
  img: () => null,
};

const ALLOWED = ['p', 'strong', 'em', 'del', 'code', 'a', 'br'] as const;

export const InlineMarkdown = memo(function InlineMarkdown({ text }: Props) {
  if (!text) return null;
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      allowedElements={[...ALLOWED]}
      unwrapDisallowed
      components={inlineComponents}
    >
      {text}
    </ReactMarkdown>
  );
});
