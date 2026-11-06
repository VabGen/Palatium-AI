/**
 * Side pane for a server-authoritative ContentDocument (ADR 0006).
 * Chat steers; the pane holds the editable-looking result surface (Claude/Gemini).
 */
import { useEffect, useRef } from 'react';
import {
  Copy,
  Download,
  LoaderCircle,
  RotateCw,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';

import { t } from '../i18n';
import type { ContentDocument, DocumentRevision } from '../types/contentDocument';
import { BlockRenderer } from './BlockRenderer';
import { CitationSources } from './CitationSources';
import { RevisionNote } from './RevisionNote';
import { displaySourceRefs } from '../lib/attachments';

export type ArtifactPaneProps = {
  document: ContentDocument;
  revision?: DocumentRevision | null;
  messageId: string;
  userId: string;
  orgId: string;
  busy: boolean;
  feedbackLike?: boolean;
  feedbackDislike?: boolean;
  feedbackSending?: boolean;
  regenerating?: boolean;
  onClose: () => void;
  onLike: () => void;
  onDislike: () => void;
  onCopy: () => void;
  onExportPdf: () => void;
  onRegenerate: () => void;
};

export function ArtifactPane({
  document,
  revision,
  messageId,
  userId,
  orgId,
  busy,
  feedbackLike,
  feedbackDislike,
  feedbackSending,
  regenerating,
  onClose,
  onLike,
  onDislike,
  onCopy,
  onExportPdf,
  onRegenerate,
}: ArtifactPaneProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const citationAnchors = document.meta.citations ?? [];
  const sourceChips = displaySourceRefs(document.meta.source_refs);
  const title = document.title?.trim() || t('artifact.untitled');

  useEffect(() => {
    closeRef.current?.focus();
  }, [messageId]);

  return (
    <aside
      className="artifact-pane"
      part="artifact"
      aria-label={t('artifact.paneLabel')}
      data-message-id={messageId}
    >
      <header className="artifact-pane-header">
        <div className="artifact-pane-heading">
          <p className="artifact-pane-kicker">{t('artifact.kicker')}</p>
          <h2 className="artifact-pane-title">{title}</h2>
        </div>
        <button
          ref={closeRef}
          type="button"
          className="artifact-pane-close"
          onClick={onClose}
          aria-label={t('artifact.close')}
          title={t('artifact.close')}
        >
          <X size={16} aria-hidden />
        </button>
      </header>

      <div className="artifact-pane-body">
        <RevisionNote revision={revision} />
        <BlockRenderer document={document} revision={revision} />
        {citationAnchors.length > 0 ? (
          <CitationSources citations={citationAnchors} userId={userId} orgId={orgId} />
        ) : sourceChips.length > 0 ? (
          <ul className="source-ref-chips" aria-label={t('attach.sources')}>
            {sourceChips.map((ref, index) => (
              <li key={ref} id={`artifact-source-ref-${index + 1}`} className="source-ref-chip">
                <span className="source-ref-index" aria-hidden>
                  {index + 1}
                </span>
                {ref}
              </li>
            ))}
          </ul>
        ) : null}
      </div>

      <footer className="artifact-pane-footer msg-actions">
        <button
          type="button"
          className={`action-btn ${feedbackLike ? 'active' : ''}`}
          onClick={onLike}
          disabled={feedbackSending || busy}
          aria-pressed={!!feedbackLike}
          aria-label={t('action.like')}
        >
          <ThumbsUp size={16} />
        </button>
        <button
          type="button"
          className={`action-btn ${feedbackDislike ? 'active' : ''}`}
          onClick={onDislike}
          disabled={feedbackSending || busy}
          aria-pressed={!!feedbackDislike}
          aria-label={t('action.dislike')}
        >
          <ThumbsDown size={16} />
        </button>
        <button
          type="button"
          className="action-btn"
          onClick={onCopy}
          disabled={busy}
          aria-label={t('action.copy')}
        >
          <Copy size={16} />
        </button>
        <button
          type="button"
          className="action-btn"
          onClick={onExportPdf}
          disabled={busy}
          aria-label={t('action.exportPdf')}
        >
          <Download size={16} />
        </button>
        <button
          type="button"
          className="action-btn"
          onClick={onRegenerate}
          disabled={busy || regenerating}
          aria-label={t('action.regenerate')}
        >
          {regenerating ? <LoaderCircle className="spin" size={16} /> : <RotateCw size={16} />}
        </button>
      </footer>
    </aside>
  );
}
