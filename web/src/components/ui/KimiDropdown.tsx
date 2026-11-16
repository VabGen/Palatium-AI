import { useEffect, useId, useRef, useState, type ReactNode, type RefObject } from 'react';
import { IconCheck, IconChevronDown } from '../../icons/kimiStroke';
import { PopoverSurface } from './PopoverSurface';

export type KimiDropdownOption = {
  id: string;
  label: string;
  description?: string;
};

export type KimiDropdownProps = {
  label: string;
  value: string;
  options: readonly KimiDropdownOption[];
  onChange: (id: string) => void;
  /** Extra class on the trigger button */
  className?: string;
  align?: 'start' | 'end';
};

/**
 * Kimi chrome dropdown — Color System elevated surface + hairline border.
 * Open motion (opacity + translateY) lives in CSS for K4 polish.
 */
export function KimiDropdown({
  label,
  value,
  options,
  onChange,
  className = '',
  align = 'start',
}: KimiDropdownProps) {
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const selected = options.find(o => o.id === value) ?? options[0];

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div className={`kimi-dd${open ? ' is-open' : ''} ${className}`.trim()} ref={rootRef}>
      <button
        type="button"
        className="kimi-dd__trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={label}
        onClick={() => setOpen(v => !v)}
      >
        <span className="kimi-dd__value">{selected?.label ?? label}</span>
        <IconChevronDown size={14} className="kimi-dd__chevron" />
      </button>
      <PopoverSurface
        open={open}
        rootRef={rootRef}
        align={align}
        id={listId}
        className={`kimi-dd__menu kimi-dd__menu--${align}`}
        role="listbox"
        label={label}
        as="ul"
        onDismiss={() => setOpen(false)}
      >
        {options.map(opt => {
          const isActive = opt.id === value;
          return (
            <li key={opt.id} role="presentation">
              <button
                type="button"
                role="option"
                aria-selected={isActive}
                className={`kimi-dd__item${isActive ? ' is-active' : ''}`}
                onClick={() => {
                  onChange(opt.id);
                  setOpen(false);
                }}
              >
                <span className="kimi-dd__item-text">
                  <span className="kimi-dd__item-label">{opt.label}</span>
                  {opt.description ? (
                    <span className="kimi-dd__item-desc">{opt.description}</span>
                  ) : null}
                </span>
                {isActive ? <IconCheck size={14} /> : null}
              </button>
            </li>
          );
        })}
      </PopoverSurface>
    </div>
  );
}

export type KimiMenuProps = {
  trigger: ReactNode;
  label: string;
  children: ReactNode;
  align?: 'start' | 'end';
  /** Profile foot menus open upward so they stay in view. */
  placement?: 'bottom' | 'top';
  triggerClassName?: string;
  /** Portaled menu gets its own class hook (width/row chrome per surface). */
  menuClassName?: string;
  /**
   * Anchor override. kimi.ai hangs the foot menu off the footer card, not the
   * avatar button, so the panel stays flush with the sidebar inset.
   */
  anchorRef?: RefObject<HTMLElement | null>;
  /** Trigger-to-panel gap when the anchor is a larger box than the trigger. */
  gap?: number;
};

/** Generic menu shell (profile / settings) with same elevated surface. */
export function KimiMenu({
  trigger,
  label,
  children,
  align = 'end',
  placement = 'bottom',
  triggerClassName = 'kimi-dd__trigger--icon',
  menuClassName = '',
  anchorRef,
  gap,
}: KimiMenuProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const menuId = useId();

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [open]);

  return (
    <div
      className={`kimi-dd${open ? ' is-open' : ''}${placement === 'top' ? ' kimi-dd--up' : ''}`}
      ref={rootRef}
    >
      <button
        type="button"
        className={`kimi-dd__trigger ${triggerClassName}`.trim()}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        aria-label={label}
        onClick={() => setOpen(v => !v)}
      >
        {trigger}
      </button>
      <PopoverSurface
        open={open}
        rootRef={rootRef}
        anchorRef={anchorRef}
        side={placement === 'top' ? 'top' : 'bottom'}
        align={align}
        gap={gap}
        id={menuId}
        className={`kimi-dd__menu kimi-dd__menu--${align}${
          placement === 'top' ? ' kimi-dd__menu--up' : ''
        }${menuClassName ? ` ${menuClassName}` : ''}`}
        role="menu"
        label={label}
        onDismiss={() => setOpen(false)}
        onClick={event => {
          // kimi.ai closes the menu as soon as one of its actions fires.
          if ((event.target as HTMLElement).closest('button, [role="menuitem"]')) {
            setOpen(false);
          }
        }}
      >
        {children}
      </PopoverSurface>
    </div>
  );
}
