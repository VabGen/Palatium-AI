import { memo, useMemo } from 'react';
import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

type Props = {
  text: string;
  /** Filenames for ``[n]`` chips; index 0 = cite ``[1]``. Absent → markers stay plain. */
  sourceRefs?: readonly string[];
};

/**
 * Inline GFM subset for ContentDocument string fields.
 * Formatter streams ``**bold**`` / ``*italic*``; BlockRenderer must not show markers.
 * Block constructs (tables, lists, headings) are disallowed — structure already
 * lives in typed blocks; cells stay inline-only.
 *
 * Resolvable ``[n]`` become cite chips (Big Tech grounding) when ``sourceRefs`` is set.
 */
const inlineComponents: Components = {
  p: ({ children }) => <>{children}</>,
  a: ({ children }) => <span>{children}</span>,
  img: () => null,
};

const ALLOWED = ['p', 'strong', 'em', 'del', 'code', 'a', 'br'] as const;
const CITE_RE = /\[(\d{1,2})\](?!\()/g;

type Segment =
  | { kind: 'text'; value: string }
  | { kind: 'cite'; n: number; label: string };

function splitCites(text: string, sourceRefs: readonly string[]): Segment[] {
  if (!text || sourceRefs.length === 0) {
    return text ? [{ kind: 'text', value: text }] : [];
  }
  const parts: Segment[] = [];
  let last = 0;
  for (const match of text.matchAll(CITE_RE)) {
    const n = Number(match[1]);
    const index = match.index ?? 0;
    if (index > last) {
      parts.push({ kind: 'text', value: text.slice(last, index) });
    }
    if (n >= 1 && n <= sourceRefs.length) {
      parts.push({ kind: 'cite', n, label: sourceRefs[n - 1] ?? String(n) });
    } else {
      parts.push({ kind: 'text', value: match[0] });
    }
    last = index + match[0].length;
  }
  if (last < text.length) {
    parts.push({ kind: 'text', value: text.slice(last) });
  }
  return parts;
}

const MarkdownBit = memo(function MarkdownBit({ text }: { text: string }) {
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

export const InlineMarkdown = memo(function InlineMarkdown({ text, sourceRefs = [] }: Props) {
  const segments = useMemo(() => splitCites(text, sourceRefs), [text, sourceRefs]);
  if (!text) return null;
  if (sourceRefs.length === 0) {
    return <MarkdownBit text={text} />;
  }
  return (
    <>
      {segments.map((segment, index) => {
        if (segment.kind === 'text') {
          return <MarkdownBit key={`t-${index}`} text={segment.value} />;
        }
        return (
          <a
            key={`c-${index}-${segment.n}`}
            className="cite-marker"
            href={`#source-ref-${segment.n}`}
            title={segment.label}
            aria-label={`${segment.n}: ${segment.label}`}
          >
            {segment.n}
          </a>
        );
      })}
    </>
  );
});
