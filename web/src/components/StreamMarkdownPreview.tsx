import type { Components } from 'react-markdown';
import ReactMarkdown, { defaultUrlTransform } from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { TokenIcon } from '../icons/TokenIcon';
import {
  ICON_MD_SCHEME,
  iconTokenFromMdSrc,
  sanitizeStreamMarkdown,
} from '../lib/markdown';

type Props = {
  markdown: string;
};

/** Allow our opaque icon scheme; keep default sanitization for everything else. */
function streamUrlTransform(url: string): string {
  if (url.startsWith(ICON_MD_SCHEME)) return url;
  return defaultUrlTransform(url);
}

/** Lightweight element map — headings / lists / tables / code + TokenIcon. */
const previewComponents: Components = {
  h1: ({ children }) => <h3 className="stream-md-h">{children}</h3>,
  h2: ({ children }) => <h3 className="stream-md-h">{children}</h3>,
  h3: ({ children }) => <h3 className="stream-md-h">{children}</h3>,
  h4: ({ children }) => <h4 className="stream-md-h">{children}</h4>,
  ul: ({ children }) => <ul className="stream-md-list">{children}</ul>,
  ol: ({ children }) => <ol className="stream-md-list">{children}</ol>,
  table: ({ children }) => (
    <div className="stream-md-table-wrap">
      <table>{children}</table>
    </div>
  ),
  pre: ({ children }) => <pre className="stream-md-pre">{children}</pre>,
  code: ({ children, className }) =>
    className ? <code className={className}>{children}</code> : <code>{children}</code>,
  // Never make stream XML look clickable — HITL only from result cards (020).
  a: ({ children }) => <span>{children}</span>,
  // Icon tokens are rewritten to ``![icon](palatium-icon:NAME)`` in sanitize.
  img: ({ src }) => {
    const token = iconTokenFromMdSrc(src);
    if (token) {
      return <TokenIcon token={token} size={16} className="stream-md-icon" />;
    }
    // Unknown / non-icon images: never fetch remote URLs in stream preview.
    if (src?.startsWith('palatium-icon:')) {
      return <TokenIcon token={undefined} size={16} className="stream-md-icon" />;
    }
    return null;
  },
};

/**
 * Progressive GFM preview during SSE (Path C).
 * Icon tokens render via TokenIcon (same as BlockRenderer); HITL/emoji stripped.
 */
export function StreamMarkdownPreview({ markdown }: Props) {
  const cleaned = sanitizeStreamMarkdown(markdown);
  if (!cleaned.trim()) {
    return null;
  }
  return (
    <div className="stream-preview stream-preview--md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        urlTransform={streamUrlTransform}
        components={previewComponents}
      >
        {cleaned}
      </ReactMarkdown>
    </div>
  );
}
