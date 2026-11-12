/**
 * Side pane for a server-authoritative ContentDocument (ADR 0006).
 * Chat steers; the pane holds the editable-looking result surface (Claude/Gemini).
 */
import { useEffect, useRef } from 'react';
import { KimiActionIcon } from '../icons/kimiActionIcons';
import { IconDownload, IconLoader, IconX } from '../icons/kimiStroke';
import { t } from '../i18n';
import type { ContentDocument, DocumentRevision } from '../types/contentDocument';
import { BlockRenderer } from './BlockRenderer';
import { CitationSources } from './CitationSources';
import { displaySourceRefs } from '../lib/attachments';

export type ArtifactPaneProps = {
  document: ContentDocument;
  /** Kept for caller parity with the turn payload; product pane never paints W7b wash. */
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
  onShare?: () => void;
  onExportPdf: () => void;
  onRegenerate: () => void;
};

export function ArtifactPane({
  document,
  revision: _revision,
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
  onShare,
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
          <IconX size={16} />
        </button>
      </header>

      <div className="artifact-pane-body">
        {/* Product surface: final answer only — revision wash is chat/dev chrome. */}
        <BlockRenderer document={document} revision={null} />
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

      <footer className="artifact-pane-footer msg-actions msg-actions--product">
        <button
          type="button"
          className={`icon-btn icon-btn--sm${feedbackLike ? ' is-active' : ''}`}
          onClick={onLike}
          disabled={feedbackSending || busy}
          aria-pressed={!!feedbackLike}
          aria-label={t('action.like')}
        >
          <KimiActionIcon name="like" size={16} />
        </button>
        <button
          type="button"
          className={`icon-btn icon-btn--sm${feedbackDislike ? ' is-active' : ''}`}
          onClick={onDislike}
          disabled={feedbackSending || busy}
          aria-pressed={!!feedbackDislike}
          aria-label={t('action.dislike')}
        >
          <KimiActionIcon name="dislike" size={16} />
        </button>
        <button
          type="button"
          className="icon-btn icon-btn--sm"
          onClick={onCopy}
          disabled={busy}
          aria-label={t('action.copy')}
        >
          <KimiActionIcon name="copy" size={16} />
        </button>
        {onShare ? (
          <button
            type="button"
            className="icon-btn icon-btn--sm"
            onClick={onShare}
            disabled={busy}
            aria-label={t('action.share')}
            title={t('action.share')}
          >
            <KimiActionIcon name="share" size={16} />
          </button>
        ) : null}
        <button
          type="button"
          className="icon-btn icon-btn--sm"
          onClick={onExportPdf}
          disabled={busy}
          aria-label={t('action.exportPdf')}
        >
          <IconDownload size={16} />
        </button>
        <button
          type="button"
          className="icon-btn icon-btn--sm"
          onClick={onRegenerate}
          disabled={busy || regenerating}
          aria-label={t('action.regenerate')}
          title={t('action.regenerate')}
        >
          {regenerating ? (
            <IconLoader className="spin" size={16} />
          ) : (
            <KimiActionIcon name="refresh" size={16} />
          )}
        </button>
      </footer>
    </aside>
  );
}
