import type { Components } from 'react-markdown';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { sanitizeStreamMarkdown } from '../lib/markdown';

type Props = {
  markdown: string;
};

/** Lightweight element map — headings / lists / tables / code only. */
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
};

/**
 * Progressive GFM preview during SSE (Hybrid Phase 1 / hotfix 1.1).
 * Icon tokens and emoji are stripped; final UI uses BlockRenderer + library icons.
 */
export function StreamMarkdownPreview({ markdown }: Props) {
  const cleaned = sanitizeStreamMarkdown(markdown);
  if (!cleaned.trim()) {
    return null;
  }
  return (
    <div className="stream-preview stream-preview--md">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={previewComponents}>
        {cleaned}
      </ReactMarkdown>
    </div>
  );
}
