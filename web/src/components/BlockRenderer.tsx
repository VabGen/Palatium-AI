import { memo, useMemo } from 'react';
import { TokenIcon } from '../icons/TokenIcon';
import { iconForStepStatus, iconForTone } from '../icons/semanticIcons';
import { InlineMarkdown } from './InlineMarkdown';
import { WidgetEmbed } from './WidgetEmbed';
import { t } from '../i18n';
import { changedBlockIndices } from '../lib/revision';
import type {
  CalloutBlock,
  ChartBlock,
  CodeBlock,
  ContentBlock,
  ContentDocument,
  DocumentRevision,
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
  /**
   * Diff против предыдущего ответа (W7b). Индексы изменённых блоков приходят с
   * сервера — см. `DocumentRevision.changed_block_indices`.
   */
  revision?: DocumentRevision | null;
};

/** Long answers: keep lead sections open; collapse later H2/H3 sections (any scenario). */
const COLLAPSE_AFTER_SECTIONS = 2;
const MIN_BLOCKS_FOR_COLLAPSE = 8;

type DocSection = {
  headingIndex: number | null;
  bodyIndices: number[];
};

function groupDocSections(blocks: readonly ContentBlock[]): DocSection[] {
  const sections: DocSection[] = [];
  let current: DocSection = { headingIndex: null, bodyIndices: [] };
  const push = () => {
    if (current.headingIndex !== null || current.bodyIndices.length > 0) {
      sections.push(current);
    }
  };
  blocks.forEach((block, index) => {
    if (block.type === 'heading' && block.level <= 2) {
      push();
      current = { headingIndex: index, bodyIndices: [] };
      return;
    }
    current.bodyIndices.push(index);
  });
  push();
  return sections;
}

export const BlockRenderer = memo(({ document, revision }: BlockRendererProps) => {
  const changed = useMemo(() => changedBlockIndices(revision), [revision]);
  const sections = useMemo(() => groupDocSections(document.blocks), [document.blocks]);
  const sourceRefs = document.meta.source_refs ?? [];
  const collapseTail =
    sections.length > COLLAPSE_AFTER_SECTIONS && document.blocks.length >= MIN_BLOCKS_FOR_COLLAPSE;

  const renderIndexed = (index: number) => {
    const block = document.blocks[index];
    if (!block) return null;
    const key = `${block.type}-${index}`;
    if (!changed.has(index)) {
      return <BlockView key={key} block={block} sourceRefs={sourceRefs} />;
    }
    return (
      <div key={key} className="doc-block-changed" data-revision="changed">
        <span className="sr-only">{t('revision.changedBlock')}</span>
        <BlockView block={block} sourceRefs={sourceRefs} />
      </div>
    );
  };

  return (
    <article className="doc" lang={document.locale}>
      {document.title && (
        <header className="doc-title">
          <InlineMarkdown text={document.title} />
        </header>
      )}
      <div className="doc-blocks">
        {sections.map((section, sectionIndex) => {
          const collapse =
            collapseTail &&
            sectionIndex >= COLLAPSE_AFTER_SECTIONS &&
            section.headingIndex !== null;
          const heading =
            section.headingIndex !== null ? document.blocks[section.headingIndex] : null;
          const body = section.bodyIndices.map(renderIndexed);
          if (collapse && heading && heading.type === 'heading') {
            return (
              <details key={`section-${sectionIndex}`} className="doc-section is-collapsible">
                <summary className="doc-section-summary">
                  <HeadingView block={heading} sourceRefs={sourceRefs} />
                </summary>
                <div className="doc-section-body">{body}</div>
              </details>
            );
          }
          return (
            <div key={`section-${sectionIndex}`} className="doc-section">
              {section.headingIndex !== null ? renderIndexed(section.headingIndex) : null}
              {body}
            </div>
          );
        })}
      </div>
    </article>
  );
});

type WithSources = { sourceRefs: readonly string[] };

const BlockView = memo(({ block, sourceRefs }: { block: ContentBlock } & WithSources) => {
  switch (block.type) {
    case 'heading':
      return <HeadingView block={block} sourceRefs={sourceRefs} />;
    case 'paragraph':
      return <ParagraphView block={block} sourceRefs={sourceRefs} />;
    case 'list':
      return <ListView block={block} sourceRefs={sourceRefs} />;
    case 'table':
      return <TableView block={block} sourceRefs={sourceRefs} />;
    case 'callout':
      return <CalloutView block={block} sourceRefs={sourceRefs} />;
    case 'code':
      return <CodeView block={block} />;
    case 'formula':
      return <FormulaView block={block} />;
    case 'kv':
      return <KeyValueView block={block} sourceRefs={sourceRefs} />;
    case 'steps':
      return <StepsView block={block} sourceRefs={sourceRefs} />;
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
const HeadingView = memo(({ block, sourceRefs }: { block: HeadingBlock } & WithSources) => {
  const Tag = `h${block.level}` as 'h1' | 'h2' | 'h3';
  return (
    <Tag className={`block-heading level-${block.level}`}>
      <TokenIcon token={block.icon} size={block.level === 1 ? 22 : 18} />
      <span>
        <InlineMarkdown text={block.text} sourceRefs={sourceRefs} />
      </span>
    </Tag>
  );
});

const ParagraphView = memo(({ block, sourceRefs }: { block: ParagraphBlock } & WithSources) => (
  <p className="block-paragraph">
    <TokenIcon token={block.icon} size={16} />
    <span>
      <InlineMarkdown text={block.text} sourceRefs={sourceRefs} />
    </span>
  </p>
));

/** Legacy text marker before ``ListItem.level`` existed (server still strips it). */
const NESTED_ITEM_PREFIX = '· ';

function listItemPresentation(item: ListBlock['items'][number]): {
  text: string;
  level: number;
} {
  let text = item.text;
  let level = typeof item.level === 'number' && item.level > 0 ? Math.min(item.level, 2) : 0;
  while (text.startsWith(NESTED_ITEM_PREFIX)) {
    text = text.slice(NESTED_ITEM_PREFIX.length);
    level = Math.max(level, 1);
  }
  return { text, level };
}

const ListView = memo(({ block, sourceRefs }: { block: ListBlock } & WithSources) => {
  const Tag = block.style === 'ordered' ? 'ol' : 'ul';
  return (
    <Tag className={`block-list style-${block.style}`}>
      {block.items.map((item, i) => {
        const { text, level } = listItemPresentation(item);
        const nestedClass = level > 0 ? ` nested level-${level}` : '';
        return (
          <li key={i} className={`block-list-item${nestedClass}`}>
            <TokenIcon token={item.icon} size={16} />
            <span>
              {item.emphasis && <strong>{item.emphasis}</strong>}
              {item.emphasis && ' — '}
              <InlineMarkdown text={text} sourceRefs={sourceRefs} />
            </span>
          </li>
        );
      })}
    </Tag>
  );
});

const TableView = memo(({ block, sourceRefs }: { block: TableBlock } & WithSources) => (
  <div className="block-table-wrap">
    <table className="block-table">
      <thead>
        <tr>
          {block.columns.map(col => (
            <th key={col}>
              <InlineMarkdown text={col} sourceRefs={sourceRefs} />
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {block.rows.map((row, ri) => (
          <tr key={ri}>
            {row.map((cell, ci) => (
              <td key={ci}>
                <InlineMarkdown text={cell} sourceRefs={sourceRefs} />
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
));

const CalloutView = memo(({ block, sourceRefs }: { block: CalloutBlock } & WithSources) => (
  <aside className={`block-callout tone-${block.tone}`}>
    <TokenIcon token={block.icon ?? iconForTone(block.tone)} size={18} animated />
    <div>
      {block.title && (
        <strong>
          <InlineMarkdown text={block.title} sourceRefs={sourceRefs} />
        </strong>
      )}
      <p>
        <InlineMarkdown text={block.body} sourceRefs={sourceRefs} />
      </p>
    </div>
  </aside>
));

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

const KeyValueView = memo(({ block, sourceRefs }: { block: KeyValueBlock } & WithSources) => (
  <dl className="block-kv">
    {block.items.map(item => (
      <div className="kv-row" key={`${item.label}-${item.value}`}>
        <dt>
          <TokenIcon token={item.icon} size={14} />
          <InlineMarkdown text={item.label} sourceRefs={sourceRefs} />
        </dt>
        <dd>
          <InlineMarkdown text={item.value} sourceRefs={sourceRefs} />
        </dd>
      </div>
    ))}
  </dl>
));

const StepsView = memo(({ block, sourceRefs }: { block: StepsBlock } & WithSources) => (
  <ol className="block-steps">
    {block.items.map((item, i) => {
      const icon = item.icon ?? iconForStepStatus(item.status);
      return (
        <li key={i} className={item.status ? `step status-${item.status}` : 'step'}>
          <div className="step-marker">
            {/*
              Маркер несёт порядковый номер, пока не известно состояние: номер —
              факт из данных, а иконка статуса без статуса была бы выдумкой
              (и одинаковой у всех строк).
            */}
            {icon ? <TokenIcon token={icon} size={16} /> : <span aria-hidden>{i + 1}</span>}
          </div>
          <div className="step-body">
            <strong>
              <InlineMarkdown text={item.title} sourceRefs={sourceRefs} />
            </strong>
            <p>
              <InlineMarkdown text={item.body} sourceRefs={sourceRefs} />
            </p>
          </div>
        </li>
      );
    })}
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
