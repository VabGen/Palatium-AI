import { useEffect, useId, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import { IconX } from '../icons/kimiStroke';

export type KimiDialogProps = {
  open: boolean;
  title: string;
  description?: string;
  /** Extra copy under the title (kept as plain text — dialogs never take HTML). */
  closeLabel: string;
  onClose: () => void;
  children?: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md';
};

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

const FIELD =
  'textarea:not([disabled]), input:not([disabled]):not([type="hidden"]):not([type="button"]):not([type="submit"]):not([type="reset"]), select:not([disabled])';

/**
 * Kimi-style centered dialog (scrim + elevated surface).
 *
 * Portal is deliberate: the shell stage is a scroll container with its own
 * stacking context, so an in-flow modal would be clipped by `overflow: auto`
 * and painted under sibling cards. Focus is trapped inside the panel and the
 * previous focus is restored on close — keyboard users never lose their place.
 *
 * Initial focus prefers `[data-autofocus]` / the first field over the close
 * button. The open effect depends only on `open` so typing (parent re-renders
 * with a fresh `onClose`) never steals focus back to the X.
 */
export function KimiDialog({
  open,
  title,
  description,
  closeLabel,
  onClose,
  children,
  footer,
  size = 'sm',
}: KimiDialogProps) {
  const titleId = useId();
  const descId = useId();
  const panelRef = useRef<HTMLDivElement | null>(null);
  const restoreRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    restoreRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const panel = panelRef.current;
      if (!panel) return;
      const nodes = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE));
      if (nodes.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = nodes[0]!;
      const last = nodes[nodes.length - 1]!;
      const active = document.activeElement;
      const inside = active instanceof Node && panel.contains(active);
      if (event.shiftKey && (!inside || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!inside || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const raf = requestAnimationFrame(() => {
      const panel = panelRef.current;
      if (!panel) return;
      const target =
        panel.querySelector<HTMLElement>('[data-autofocus]') ??
        panel.querySelector<HTMLElement>(FIELD) ??
        panel.querySelector<HTMLElement>(FOCUSABLE);
      target?.focus();
    });

    return () => {
      cancelAnimationFrame(raf);
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
      restoreRef.current?.focus?.();
      restoreRef.current = null;
    };
  }, [open]);

  if (!open) return null;

  return createPortal(
    <div
      className="kimi-modal"
      role="presentation"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onCloseRef.current();
      }}
    >
      <div
        ref={panelRef}
        className={`kimi-modal__panel kimi-modal__panel--${size}`}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descId : undefined}
        tabIndex={-1}
      >
        <div className="kimi-modal__head">
          <h2 id={titleId} className="kimi-modal__title">
            {title}
          </h2>
          <button
            type="button"
            className="kimi-modal__close icon-hover"
            aria-label={closeLabel}
            onClick={() => onCloseRef.current()}
          >
            <IconX size={16} />
          </button>
        </div>
        {description ? (
          <p id={descId} className="kimi-modal__desc">
            {description}
          </p>
        ) : null}
        {children ? <div className="kimi-modal__body">{children}</div> : null}
        {footer ? <div className="kimi-modal__foot">{footer}</div> : null}
      </div>
    </div>,
    document.body
  );
}
