import { memo } from 'react';
import { TokenIcon } from '../icons/TokenIcon';
import { WidgetEmbed } from './WidgetEmbed';
import type {
  CalloutBlock,
  ChartBlock,
  CodeBlock,
  ContentBlock,
  ContentDocument,
  FormulaBlock,
  HeadingBlock,
  KeyValueBlock,
  ListBlock,
  ParagraphBlock,
  StepsBlock,
  TableBlock,
  WidgetBlock,
} from '../types/contentDocument';

type BlockRendererProps = {
  document: ContentDocument;
};

export const BlockRenderer = memo(({ document }: BlockRendererProps) => {
  return (
    <article className="doc" lang={document.locale}>
      {document.title && <header className="doc-title">{document.title}</header>}
      <div className="doc-blocks">
        {document.blocks.map((block, index) => (
          <BlockView key={`${block.type}-${index}`} block={block} />
        ))}
      </div>
    </article>
  );
});

const BlockView = memo(({ block }: { block: ContentBlock }) => {
  switch (block.type) {
    case 'heading':
      return <HeadingView block={block} />;
    case 'paragraph':
      return <ParagraphView block={block} />;
    case 'list':
      return <ListView block={block} />;
    case 'table':
      return <TableView block={block} />;
    case 'callout':
      return <CalloutView block={block} />;
    case 'code':
      return <CodeView block={block} />;
    case 'formula':
      return <FormulaView block={block} />;
    case 'kv':
      return <KeyValueView block={block} />;
    case 'steps':
      return <StepsView block={block} />;
    case 'chart':
      return <ChartView block={block} />;
    case 'divider':
      return <hr className="block-divider" />;
    case 'widget':
      return <WidgetView block={block} />;
    default:
      return null;
  }
});

// ---- Вьюхи с мемоизацией ----
const HeadingView = memo(({ block }: { block: HeadingBlock }) => {
  const Tag = `h${block.level}` as 'h1' | 'h2' | 'h3';
  return (
    <Tag className={`block-heading level-${block.level}`}>
      <TokenIcon token={block.icon} size={block.level === 1 ? 22 : 18} />
      <span>{block.text}</span>
    </Tag>
  );
});

const ParagraphView = memo(({ block }: { block: ParagraphBlock }) => (
  <p className="block-paragraph">{block.text}</p>
));

const ListView = memo(({ block }: { block: ListBlock }) => {
  const Tag = block.style === 'ordered' ? 'ol' : 'ul';
  return (
    <Tag className={`block-list style-${block.style}`}>
      {block.items.map((item, i) => (
        <li key={i}>
          <TokenIcon token={item.icon} size={16} />
          <span>
            {item.emphasis && <strong>{item.emphasis}</strong>}
            {item.emphasis && ' — '}
            {item.text}
          </span>
        </li>
      ))}
    </Tag>
  );
});

const TableView = memo(({ block }: { block: TableBlock }) => (
  <div className="block-table-wrap">
    <table className="block-table">
      <thead>
        <tr>
          {block.columns.map(col => (
            <th key={col}>{col}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {block.rows.map((row, ri) => (
          <tr key={ri}>
            {row.map((cell, ci) => (
              <td key={ci}>{cell}</td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
));

const CalloutView = memo(({ block }: { block: CalloutBlock }) => {
  const icon =
    block.icon ??
    (block.tone === 'danger'
      ? 'danger'
      : block.tone === 'warning'
        ? 'warning'
        : block.tone === 'success'
          ? 'success'
          : 'info');
  return (
    <aside className={`block-callout tone-${block.tone}`}>
      <TokenIcon token={icon} size={18} animated />
      <div>
        {block.title && <strong>{block.title}</strong>}
        <p>{block.body}</p>
      </div>
    </aside>
  );
});

const CodeView = memo(({ block }: { block: CodeBlock }) => (
  <pre className="block-code">
    <code data-language={block.language}>{block.content}</code>
  </pre>
));

const FormulaView = memo(({ block }: { block: FormulaBlock }) => (
  <div className="block-formula" title="LaTeX">
    <code>{block.latex}</code>
  </div>
));

const KeyValueView = memo(({ block }: { block: KeyValueBlock }) => (
  <dl className="block-kv">
    {block.items.map(item => (
      <div className="kv-row" key={`${item.label}-${item.value}`}>
        <dt>
          <TokenIcon token={item.icon} size={14} />
          {item.label}
        </dt>
        <dd>{item.value}</dd>
      </div>
    ))}
  </dl>
));

const StepsView = memo(({ block }: { block: StepsBlock }) => (
  <ol className="block-steps">
    {block.items.map((item, i) => (
      <li key={i} className={`step status-${item.status}`}>
        <div className="step-marker">
          <TokenIcon token={item.icon ?? 'check'} size={16} />
        </div>
        <div className="step-body">
          <strong>{item.title}</strong>
          <p>{item.body}</p>
        </div>
      </li>
    ))}
  </ol>
));

const ChartView = memo(({ block }: { block: ChartBlock }) => {
  const series = block.series[0];
  if (!series) return null;
  const max = Math.max(...series.values, 1);
  const w = 320;
  const h = 140;
  const pad = 16;
  const barW = (w - pad * 2) / series.values.length;

  if (block.kind === 'line') {
    const points = series.values
      .map((v, i) => {
        const x = pad + i * barW + barW / 2;
        const y = h - pad - (v / max) * (h - pad * 2);
        return `${x},${y}`;
      })
      .join(' ');
    return (
      <figure className="block-chart">
        {block.title && <figcaption>{block.title}</figcaption>}
        <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={block.title ?? series.name}>
          <polyline fill="none" stroke="var(--accent)" strokeWidth="2.5" points={points} />
        </svg>
        <div className="chart-labels">
          {block.labels.map(label => (
            <span key={label}>{label}</span>
          ))}
        </div>
      </figure>
    );
  }

  return (
    <figure className="block-chart">
      {block.title && <figcaption>{block.title}</figcaption>}
      <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={block.title ?? series.name}>
        {series.values.map((v, i) => {
          const bh = (v / max) * (h - pad * 2);
          const x = pad + i * barW + 4;
          const y = h - pad - bh;
          return (
            <rect
              key={block.labels[i] ?? i}
              x={x}
              y={y}
              width={Math.max(barW - 8, 4)}
              height={bh}
              rx={3}
              fill="var(--accent)"
              opacity={0.85}
            />
          );
        })}
      </svg>
      <div className="chart-labels">
        {block.labels.map(label => (
          <span key={label}>{label}</span>
        ))}
      </div>
    </figure>
  );
});

const WidgetView = memo(({ block }: { block: WidgetBlock }) => <WidgetEmbed block={block} />);
