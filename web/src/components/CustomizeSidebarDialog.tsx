import { useEffect, useRef, useState, type ReactElement } from 'react';
import { createPortal } from 'react-dom';
import { IconInfo, IconX } from '../icons/kimiStroke';
import { t } from '../i18n';

export type SidebarFeature = {
  id: string;
  label: string;
  icon: (props: { size?: number }) => ReactElement;
};

export type CustomizeSidebarValue = {
  pinned: readonly string[];
  order: readonly string[];
};

export type CustomizeSidebarDialogProps = {
  features: readonly SidebarFeature[];
  value: CustomizeSidebarValue;
  onClose: () => void;
  onSave: (value: CustomizeSidebarValue) => void;
};

type Row = SidebarFeature & { pinned: boolean };

function orderRows(features: readonly SidebarFeature[], order: readonly string[]): Row[] {
  const rank = new Map(order.map((id, index) => [id, index]));
  return [...features]
    .sort((a, b) => (rank.get(a.id) ?? 999) - (rank.get(b.id) ?? 999))
    .map(feature => ({ ...feature, pinned: false }));
}

/**
 * Kimi `.customize-sidebar-modal` — pin/reorder features in the sidebar.
 *
 * Mounted only while open, so the draft resets on every launch; rows are
 * toggled and dragged locally and the rail changes after Save. A dismissed
 * dialog therefore leaves the sidebar untouched.
 */
export function CustomizeSidebarDialog({
  features,
  value,
  onClose,
  onSave,
}: CustomizeSidebarDialogProps) {
  const pinned = new Set(value.pinned);
  const [rows, setRows] = useState<Row[]>(() =>
    orderRows(features, value.order).map(row => ({ ...row, pinned: pinned.has(row.id) }))
  );
  const dragIdRef = useRef<string | null>(null);
  const [draggingId, setDraggingId] = useState<string | null>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const openerRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    openerRef.current = document.activeElement as HTMLElement | null;
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose();
        return;
      }
      if (event.key !== 'Tab') return;
      const root = dialogRef.current;
      if (!root) return;
      const focusable = Array.from(
        root.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])'
        )
      ).filter(element => element.offsetParent !== null);
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (!first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = previousOverflow;
      openerRef.current?.focus?.();
    };
  }, [onClose]);

  const toggle = (id: string) => {
    setRows(prev => prev.map(row => (row.id === id ? { ...row, pinned: !row.pinned } : row)));
  };

  const move = (id: string, delta: number) => {
    setRows(prev => {
      const index = prev.findIndex(row => row.id === id);
      const next = index + delta;
      if (index < 0 || next < 0 || next >= prev.length) return prev;
      const copy = [...prev];
      const [row] = copy.splice(index, 1);
      if (!row) return prev;
      copy.splice(next, 0, row);
      return copy;
    });
  };

  const dropOn = (targetId: string) => {
    const sourceId = dragIdRef.current;
    if (!sourceId || sourceId === targetId) return;
    setRows(prev => {
      const from = prev.findIndex(row => row.id === sourceId);
      const to = prev.findIndex(row => row.id === targetId);
      if (from < 0 || to < 0) return prev;
      const copy = [...prev];
      const [row] = copy.splice(from, 1);
      if (!row) return prev;
      copy.splice(to, 0, row);
      return copy;
    });
  };

  const save = () => {
    onSave({
      pinned: rows.filter(row => row.pinned).map(row => row.id),
      order: rows.map(row => row.id),
    });
  };

  return createPortal(
    <div
      className="modal-mask"
      role="presentation"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        ref={dialogRef}
        className="customize-sidebar-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="customize-sidebar-title"
      >
        <header className="customize-sidebar-modal__head">
          <h2 id="customize-sidebar-title" className="customize-sidebar-modal__title">
            {t('sidebar.customize')}
          </h2>
          <button
            type="button"
            ref={closeRef}
            className="create-task-modal__close"
            aria-label={t('dialog.close')}
            onClick={onClose}
          >
            <IconX size={18} />
          </button>
        </header>

        <p className="customize-sidebar__tip">
          <span>{t('sidebar.customizeTip')}</span>
          <IconInfo size={18} />
        </p>

        <ul className="customize-sidebar__list">
          {rows.map((row, index) => {
            const Icon = row.icon;
            return (
              <li
                key={row.id}
                className={`customize-sidebar__row${draggingId === row.id ? ' is-dragging' : ''}`}
                draggable
                onDragStart={event => {
                  dragIdRef.current = row.id;
                  setDraggingId(row.id);
                  event.dataTransfer.effectAllowed = 'move';
                  event.dataTransfer.setData('text/plain', row.id);
                }}
                onDragEnd={() => {
                  dragIdRef.current = null;
                  setDraggingId(null);
                }}
                onDragOver={event => {
                  if (!dragIdRef.current) return;
                  event.preventDefault();
                  event.dataTransfer.dropEffect = 'move';
                }}
                onDrop={event => {
                  event.preventDefault();
                  dropOn(row.id);
                  dragIdRef.current = null;
                  setDraggingId(null);
                }}
                onKeyDown={event => {
                  if (!event.altKey) return;
                  if (event.key === 'ArrowUp') {
                    event.preventDefault();
                    move(row.id, -1);
                  }
                  if (event.key === 'ArrowDown') {
                    event.preventDefault();
                    move(row.id, 1);
                  }
                }}
                tabIndex={0}
                aria-label={t('sidebar.customizeDrag', { name: row.label })}
                aria-posinset={index + 1}
                aria-setsize={rows.length}
              >
                <span className="customize-sidebar__grip" aria-hidden>
                  <span />
                  <span />
                  <span />
                </span>
                <Icon size={18} />
                <span className="customize-sidebar__label">{row.label}</span>
                <button
                  type="button"
                  role="switch"
                  aria-checked={row.pinned}
                  aria-label={t('sidebar.customizeRow', { name: row.label })}
                  className={`kimi-switch${row.pinned ? ' is-on' : ''}`}
                  onClick={() => toggle(row.id)}
                >
                  <span className="kimi-switch__knob" />
                </button>
              </li>
            );
          })}
        </ul>

        <footer className="customize-sidebar-modal__foot">
          <button type="button" className="task-btn task-btn--ghost" onClick={onClose}>
            {t('sidebar.cancel')}
          </button>
          <button type="button" className="task-btn task-btn--primary" onClick={save}>
            {t('sidebar.save')}
          </button>
        </footer>
      </div>
    </div>,
    document.body
  );
}
