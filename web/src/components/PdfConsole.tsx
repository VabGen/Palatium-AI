/**
 * kimi.ai file-view PDF stage: thumbnail rail + page canvas on `--bg-soft` desk.
 * Lazy-loads pdfjs-dist so the chat shell stays lean until a PDF opens.
 */
import { useEffect, useRef, useState } from 'react';
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist';
import { IconLoader } from '../icons/kimiStroke';
import { t } from '../i18n';

export type PdfConsoleProps = {
  blobUrl: string;
  page: number;
  zoom: number;
  rotation: number;
  /** When false, hide the thumbnail rail (kimi Sidebar toggle). */
  showThumbs?: boolean;
  onPageCount: (count: number) => void;
  onPageChange: (page: number) => void;
};

const THUMB_WIDTH = 72;

async function loadPdfJs() {
  const pdfjs = await import('pdfjs-dist');
  const workerUrl = (await import('pdfjs-dist/build/pdf.worker.min.mjs?url')).default;
  pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;
  return pdfjs;
}

export function PdfConsole({
  blobUrl,
  page,
  zoom,
  rotation,
  showThumbs = true,
  onPageCount,
  onPageChange,
}: PdfConsoleProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const thumbsRef = useRef<HTMLDivElement>(null);
  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [thumbUrls, setThumbUrls] = useState<string[]>([]);

  useEffect(() => {
    let cancelled = false;
    let loaded: PDFDocumentProxy | null = null;

    const run = async () => {
      setLoading(true);
      setError(null);
      setDoc(null);
      setThumbUrls([]);
      try {
        const pdfjs = await loadPdfJs();
        const task = pdfjs.getDocument(blobUrl);
        loaded = await task.promise;
        if (cancelled) {
          await loaded.destroy();
          return;
        }
        // Unmount loading UI before thumbs finish so page 1 can paint on the canvas.
        setDoc(loaded);
        onPageCount(loaded.numPages);
        setLoading(false);

        const thumbs: string[] = [];
        for (let i = 1; i <= loaded.numPages; i += 1) {
          if (cancelled) return;
          const pdfPage = await loaded.getPage(i);
          const base = pdfPage.getViewport({ scale: 1 });
          const scale = THUMB_WIDTH / base.width;
          const viewport = pdfPage.getViewport({ scale });
          const canvas = document.createElement('canvas');
          canvas.width = Math.ceil(viewport.width);
          canvas.height = Math.ceil(viewport.height);
          const ctx = canvas.getContext('2d');
          if (!ctx) continue;
          await pdfPage.render({ canvas, canvasContext: ctx, viewport }).promise;
          if (cancelled) return;
          thumbs.push(canvas.toDataURL('image/jpeg', 0.72));
          setThumbUrls([...thumbs]);
        }
      } catch (err) {
        if (cancelled) return;
        const message = err instanceof Error ? err.message : t('toast.downloadFailed');
        setError(message.slice(0, 160));
        onPageCount(0);
        setLoading(false);
      }
    };

    void run();
    return () => {
      cancelled = true;
      void loaded?.destroy();
    };
  }, [blobUrl, onPageCount]);

  useEffect(() => {
    if (loading || !doc) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    let cancelled = false;
    let renderTask: RenderTask | null = null;

    const paint = async () => {
      try {
        const pdfPage = await doc.getPage(page);
        if (cancelled) return;
        const base = pdfPage.getViewport({ scale: 1, rotation });
        const dpr = Math.min(window.devicePixelRatio || 1, 2);
        const viewport = pdfPage.getViewport({ scale: zoom * dpr, rotation });
        canvas.width = Math.ceil(viewport.width);
        canvas.height = Math.ceil(viewport.height);
        canvas.style.width = `${Math.ceil(base.width * zoom)}px`;
        canvas.style.height = `${Math.ceil(base.height * zoom)}px`;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        renderTask = pdfPage.render({ canvas, canvasContext: ctx, viewport });
        await renderTask.promise;
      } catch {
        // Cancelled / superseded renders throw; ignore.
      }
    };

    void paint();
    return () => {
      cancelled = true;
      try {
        renderTask?.cancel();
      } catch {
        // pdfjs cancel is best-effort.
      }
    };
  }, [doc, page, zoom, rotation, loading]);

  useEffect(() => {
    const rail = thumbsRef.current;
    if (!rail) return;
    const active = rail.querySelector<HTMLElement>('[data-active="true"]');
    active?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [page, thumbUrls.length, showThumbs]);

  if (loading) {
    return (
      <div className="pdf-console__state" role="status">
        <IconLoader size={20} className="spin" />
        <span>{t('attach.previewLoading')}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="pdf-console__state" role="alert">
        <p>{error}</p>
      </div>
    );
  }

  const showRail = showThumbs && thumbUrls.length > 0;

  return (
    <div className={`pdf-console${showRail ? '' : ' pdf-console--no-thumbs'}`}>
      {showRail ? (
        <nav className="pdf-console__thumbs" aria-label={t('attach.previewPages')} ref={thumbsRef}>
          {thumbUrls.map((src, index) => {
            const n = index + 1;
            return (
              <button
                key={`thumb-${n}`}
                type="button"
                className={`pdf-console__thumb${n === page ? ' is-active' : ''}`}
                data-active={n === page ? 'true' : undefined}
                onClick={() => onPageChange(n)}
                aria-label={t('attach.previewPageOf', {
                  page: String(n),
                  total: String(thumbUrls.length),
                })}
                aria-current={n === page ? 'page' : undefined}
              >
                <img src={src} alt="" />
                <span className="pdf-console__thumb-label">{n}</span>
              </button>
            );
          })}
        </nav>
      ) : null}
      <div className="pdf-console__stage">
        <canvas ref={canvasRef} className="pdf-console__canvas" />
      </div>
    </div>
  );
}
