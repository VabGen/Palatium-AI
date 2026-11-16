/**
 * kimi.ai right-rail: «Все файлы» list + PDF/image preview.
 * Toolbar mirrors live kimi artifact-header: Sidebar · title · Expand · Zoom± · Download · Close.
 */
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react';
import { issueAttachmentDownload } from '../api/client';
import { AttachmentFileIcon, attachmentFileKind } from '../icons/fileTypeIcons';
import {
  IconCompress,
  IconDownload,
  IconExpand,
  IconLoader,
  IconPanelLeft,
  IconX,
  IconZoomIn,
  IconZoomOut,
} from '../icons/kimiStroke';
import { t } from '../i18n';

const PdfConsole = lazy(() =>
  import('./PdfConsole').then(mod => ({ default: mod.PdfConsole })),
);

export type ThreadFileItem = {
  id: string;
  filename: string;
  meta: string;
};

export type FilePreviewPaneProps = {
  mode: 'list' | 'preview';
  files: readonly ThreadFileItem[];
  /** Active file when mode === 'preview'. */
  attachmentId?: string | null;
  filename?: string | null;
  /** Citation deep-link: open PDF on this 1-based page when known. */
  initialPage?: number | null;
  userId: string;
  orgId: string;
  onClose: () => void;
  onSelectFile: (id: string, filename: string) => void;
  onShowList: () => void;
};

type PreviewKind = 'pdf' | 'image' | 'other';

const ZOOM_MIN = 0.5;
const ZOOM_MAX = 2.5;
const ZOOM_STEP = 0.25;

function previewKindFor(name: string): PreviewKind {
  const kind = attachmentFileKind(name);
  if (kind === 'pdf') return 'pdf';
  if (kind === 'image') return 'image';
  return 'other';
}

function clampZoom(value: number): number {
  return Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, Math.round(value * 100) / 100));
}

type PreviewBodyProps = {
  attachmentId: string;
  filename: string;
  initialPage?: number | null;
  userId: string;
  orgId: string;
  files: readonly ThreadFileItem[];
  onClose: () => void;
  onShowList: () => void;
};

function clampPage(page: number, count: number): number {
  if (count < 1) return 1;
  return Math.min(Math.max(page, 1), count);
}

/** Remount via `key={attachmentId}` so zoom / blob state reset without setState-in-effect. */
function PreviewBody({
  attachmentId,
  filename,
  initialPage = null,
  userId,
  orgId,
  files,
  onClose,
  onShowList,
}: PreviewBodyProps) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [zoom, setZoom] = useState(1);
  const [page, setPage] = useState(() =>
    typeof initialPage === 'number' && initialPage >= 1 ? initialPage : 1
  );
  const [pageCount, setPageCount] = useState(0);
  const [fullscreen, setFullscreen] = useState(false);
  const [showThumbs, setShowThumbs] = useState(true);
  const kind = previewKindFor(filename);

  const onPageCount = useCallback((count: number) => {
    setPageCount(count);
    setPage(current => clampPage(current, count));
  }, []);

  useEffect(() => {
    if (typeof initialPage !== 'number' || initialPage < 1) return;
    setPage(pageCount > 0 ? clampPage(initialPage, pageCount) : initialPage);
  }, [initialPage, pageCount]);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let objectUrl: string | null = null;

    const load = async () => {
      try {
        const ticket = await issueAttachmentDownload(attachmentId, userId, orgId);
        const res = await fetch(ticket.download_url);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const blob = await res.blob();
        objectUrl = URL.createObjectURL(blob);
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        setBlobUrl(objectUrl);
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : t('toast.downloadFailed');
        setError(message.slice(0, 160));
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [attachmentId, orgId, userId]);

  useEffect(() => {
    if (!fullscreen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setFullscreen(false);
    };
    const { overflow } = document.body.style;
    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', onKey);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener('keydown', onKey);
    };
  }, [fullscreen]);

  useEffect(() => {
    if (kind !== 'pdf' || pageCount < 1) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'ArrowLeft' || event.key === 'PageUp') {
        event.preventDefault();
        setPage(current => Math.max(1, current - 1));
      } else if (event.key === 'ArrowRight' || event.key === 'PageDown') {
        event.preventDefault();
        setPage(current => Math.min(pageCount, current + 1));
      }
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [kind, pageCount]);

  const download = () => {
    if (!blobUrl) return;
    const anchor = document.createElement('a');
    anchor.href = blobUrl;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  };

  return (
    <aside
      className={`file-preview-pane artifact-pane${kind === 'pdf' ? ' is-pdf' : ''}${
        fullscreen ? ' is-fullscreen' : ''
      }`}
      part="file-preview"
      aria-label={t('attach.previewLabel', { name: filename })}
      data-zone="ZONE_BODY"
    >
      <header className="file-preview-pane__header">
        <div className="file-preview-pane__heading">
          {kind === 'pdf' && pageCount > 0 ? (
            <button
              type="button"
              className="file-preview-pane__tool"
              onClick={() => setShowThumbs(value => !value)}
              aria-label={t('attach.previewThumbs')}
              title={t('attach.previewThumbs')}
              aria-pressed={showThumbs}
            >
              <IconPanelLeft size={20} />
            </button>
          ) : files.length > 0 ? (
            <button
              type="button"
              className="file-preview-pane__tool"
              onClick={onShowList}
              aria-label={t('attach.filesInChat')}
              title={t('attach.filesInChat')}
            >
              <IconPanelLeft size={20} />
            </button>
          ) : null}
          <h2 className="file-preview-pane__title" title={filename}>
            {filename}
          </h2>
        </div>
        <div className="file-preview-pane__actions">
          <button
            type="button"
            className="file-preview-pane__tool"
            onClick={() => setFullscreen(value => !value)}
            aria-label={
              fullscreen ? t('attach.previewFullscreenExit') : t('attach.previewFullscreen')
            }
            title={
              fullscreen ? t('attach.previewFullscreenExit') : t('attach.previewFullscreen')
            }
            aria-pressed={fullscreen}
          >
            {fullscreen ? <IconCompress size={20} /> : <IconExpand size={20} />}
          </button>
          <button
            type="button"
            className="file-preview-pane__tool"
            onClick={() => setZoom(value => clampZoom(value - ZOOM_STEP))}
            disabled={zoom <= ZOOM_MIN}
            aria-label={t('attach.previewZoomOut')}
            title={t('attach.previewZoomOut')}
          >
            <IconZoomOut size={20} />
          </button>
          <button
            type="button"
            className="file-preview-pane__tool"
            onClick={() => setZoom(value => clampZoom(value + ZOOM_STEP))}
            disabled={zoom >= ZOOM_MAX}
            aria-label={t('attach.previewZoomIn')}
            title={t('attach.previewZoomIn')}
          >
            <IconZoomIn size={20} />
          </button>
          <button
            type="button"
            className="file-preview-pane__tool"
            onClick={download}
            disabled={!blobUrl}
            aria-label={t('attach.download')}
            title={t('attach.download')}
          >
            <IconDownload size={20} />
          </button>
          <button
            ref={closeRef}
            type="button"
            className="file-preview-pane__tool"
            onClick={onClose}
            aria-label={t('attach.previewClose')}
            title={t('attach.previewClose')}
          >
            <IconX size={20} />
          </button>
        </div>
      </header>

      <div className="file-preview-pane__body">
        {loading ? (
          <div className="file-preview-pane__state" role="status">
            <IconLoader size={20} className="spin" />
            <span>{t('attach.previewLoading')}</span>
          </div>
        ) : error ? (
          <div className="file-preview-pane__state" role="alert">
            <AttachmentFileIcon kind={attachmentFileKind(filename)} size={48} />
            <p>{error}</p>
            <button type="button" className="file-preview-pane__retry" onClick={onClose}>
              {t('attach.previewClose')}
            </button>
          </div>
        ) : blobUrl && kind === 'pdf' ? (
          <Suspense
            fallback={
              <div className="file-preview-pane__state" role="status">
                <IconLoader size={20} className="spin" />
                <span>{t('attach.previewLoading')}</span>
              </div>
            }
          >
            <PdfConsole
              blobUrl={blobUrl}
              page={page}
              zoom={zoom}
              rotation={0}
              showThumbs={showThumbs}
              onPageCount={onPageCount}
              onPageChange={setPage}
            />
          </Suspense>
        ) : blobUrl && kind === 'image' ? (
          <div className="file-preview-pane__viewport">
            <img
              className="file-preview-pane__image"
              src={blobUrl}
              alt={filename}
              style={{ transform: `scale(${zoom})`, transformOrigin: 'center center' }}
            />
          </div>
        ) : blobUrl ? (
          <div className="file-preview-pane__state">
            <AttachmentFileIcon kind={attachmentFileKind(filename)} size={56} />
            <p className="file-preview-pane__name">{filename}</p>
            <button type="button" className="file-preview-pane__retry" onClick={download}>
              {t('attach.download')}
            </button>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

export function FilePreviewPane({
  mode,
  files,
  attachmentId = null,
  filename = null,
  initialPage = null,
  userId,
  orgId,
  onClose,
  onSelectFile,
  onShowList,
}: FilePreviewPaneProps) {
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (mode !== 'list') return;
    closeRef.current?.focus();
  }, [mode]);

  const downloadAll = useCallback(async () => {
    for (const file of files) {
      try {
        const ticket = await issueAttachmentDownload(file.id, userId, orgId);
        const anchor = document.createElement('a');
        anchor.href = ticket.download_url;
        anchor.download = file.filename;
        anchor.rel = 'noopener';
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
      } catch {
        // Per-file failure: continue the rest; toast would spam on partial sets.
      }
    }
  }, [files, orgId, userId]);

  if (mode === 'preview' && attachmentId && filename) {
    return (
      <PreviewBody
        key={attachmentId}
        attachmentId={attachmentId}
        filename={filename}
        initialPage={initialPage}
        userId={userId}
        orgId={orgId}
        files={files}
        onClose={onClose}
        onShowList={onShowList}
      />
    );
  }

  return (
    <aside
      className="file-preview-pane artifact-pane"
      part="file-preview"
      aria-label={t('attach.allFiles')}
      data-zone="ZONE_BODY"
    >
      <header className="file-preview-pane__header">
        <h2 className="file-preview-pane__title">{t('attach.allFiles')}</h2>
        <div className="file-preview-pane__actions">
          {files.length > 0 ? (
            <button
              type="button"
              className="file-preview-pane__tool"
              onClick={() => void downloadAll()}
              aria-label={t('attach.downloadAll')}
              title={t('attach.downloadAll')}
            >
              <IconDownload size={20} />
            </button>
          ) : null}
          <button
            ref={closeRef}
            type="button"
            className="file-preview-pane__tool"
            onClick={onClose}
            aria-label={t('attach.previewClose')}
            title={t('attach.previewClose')}
          >
            <IconX size={20} />
          </button>
        </div>
      </header>
      <div className="file-preview-pane__body file-preview-pane__body--list">
        {files.length === 0 ? (
          <div className="file-preview-pane__state">
            <p>{t('attach.filesEmpty')}</p>
          </div>
        ) : (
          <ul className="file-preview-pane__list">
            {files.map(file => (
              <li key={file.id}>
                <button
                  type="button"
                  className="file-preview-pane__item"
                  onClick={() => onSelectFile(file.id, file.filename)}
                >
                  <span className="file-preview-pane__item-icon" aria-hidden>
                    <AttachmentFileIcon kind={attachmentFileKind(file.filename)} size={40} />
                  </span>
                  <span className="file-preview-pane__item-text">
                    <span className="file-preview-pane__item-name">{file.filename}</span>
                    <span className="file-preview-pane__item-meta">{file.meta}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </aside>
  );
}
