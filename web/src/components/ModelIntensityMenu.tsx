import { useEffect, useId, useRef, useState } from 'react';
import { IconCheck, IconChevronRight } from '../icons/kimiStroke';
import {
  contextLengthLabelKey,
  type ContextLength,
  type ReasoningIntensity,
} from '../lib/composerModel';
import { PopoverSurface } from './ui/PopoverSurface';
import { t } from '../i18n';
import type { MessageKey } from '../i18n/messages';

export type ModelIntensityMenuProps = {
  intensity: ReasoningIntensity;
  contextLength: ContextLength;
  onIntensityChange: (value: ReasoningIntensity) => void;
  onContextLengthChange: (value: ContextLength) => void;
  disabled?: boolean;
};

const INTENSITY_KEYS = [
  ['standard', 'composer.intensity.standard'],
  ['high', 'composer.intensity.high'],
  ['max', 'composer.intensity.max'],
] as const;

const CONTEXT_LENGTH_KEYS = [
  ['standard', 'composer.contextLength.standard'],
  ['long', 'composer.contextLength.long'],
  ['max', 'composer.contextLength.max'],
] as const;

/**
 * Composer pill: «Размышление» + effort, with a real context-length submenu.
 */
export function ModelIntensityMenu({
  intensity,
  contextLength,
  onIntensityChange,
  onContextLengthChange,
  disabled,
}: ModelIntensityMenuProps) {
  const [open, setOpen] = useState(false);
  const [contextOpen, setContextOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const contextRowRef = useRef<HTMLDivElement>(null);
  const menuNodeRef = useRef<HTMLDivElement>(null);
  const submenuNodeRef = useRef<HTMLDivElement>(null);
  const closeTimerRef = useRef<number | null>(null);
  const menuId = useId();
  const submenuId = useId();

  const cancelClose = () => {
    if (closeTimerRef.current !== null) {
      window.clearTimeout(closeTimerRef.current);
      closeTimerRef.current = null;
    }
  };
  const scheduleClose = () => {
    cancelClose();
    closeTimerRef.current = window.setTimeout(() => setContextOpen(false), 120);
  };
  useEffect(() => cancelClose, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (contextOpen) setContextOpen(false);
        else setOpen(false);
      }
    };
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('keydown', onKey);
    };
  }, [contextOpen, open]);

  const effortLabel =
    intensity === 'max'
      ? t('composer.lane.effort.max')
      : intensity === 'high'
        ? t('composer.lane.effort.high')
        : t('composer.lane.effort.standard');
  const contextLabel = t(contextLengthLabelKey(contextLength) as MessageKey);

  return (
    <div className="model-lane" ref={rootRef}>
      <button
        type="button"
        className={`model-lane__trigger icon-hover${open ? ' is-open' : ''}`}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        disabled={disabled}
        onClick={() => {
          setOpen(v => !v);
          setContextOpen(false);
        }}
      >
        <span className="model-lane__name">{t('composer.intensity')}</span>
        <span className="model-lane__effort">{effortLabel}</span>
      </button>
      <PopoverSurface
        open={open}
        rootRef={rootRef}
        side="bottom"
        align="end"
        gap={4}
        id={menuId}
        className="model-lane__menu"
        role="menu"
        nodeRef={menuNodeRef}
        keepOpenRefs={[submenuNodeRef]}
        onDismiss={() => {
          setOpen(false);
          setContextOpen(false);
        }}
      >
        {INTENSITY_KEYS.map(([value, key]) => (
          <button
            key={value}
            type="button"
            role="menuitemradio"
            aria-checked={intensity === value}
            className={`kimi-dd__item model-lane__option${
              intensity === value ? ' is-selected' : ''
            }`}
            onClick={() => {
              onIntensityChange(value);
              setOpen(false);
            }}
          >
            <span className="kimi-dd__item-text">
              <span className="kimi-dd__item-label">{t(key)}</span>
            </span>
            {intensity === value ? <IconCheck size={18} className="model-lane__check" /> : null}
          </button>
        ))}
        <div className="model-lane__divider" aria-hidden />
        <div
          className="model-lane__intensity"
          ref={contextRowRef}
          onPointerEnter={() => {
            cancelClose();
            setContextOpen(true);
          }}
          onPointerLeave={scheduleClose}
        >
          <button
            type="button"
            className="kimi-dd__item"
            role="menuitem"
            aria-haspopup="menu"
            aria-expanded={contextOpen}
            aria-controls={submenuId}
            onClick={() => {
              cancelClose();
              setContextOpen(v => !v);
            }}
          >
            <span className="kimi-dd__item-label">{t('composer.contextLength')}</span>
            <span className="model-lane__value">
              <span>{contextLabel}</span>
              <IconChevronRight size={18} className="model-lane__chevron" />
            </span>
          </button>
        </div>
      </PopoverSurface>
      <PopoverSurface
        open={open && contextOpen}
        rootRef={rootRef}
        anchorRef={contextRowRef}
        edgeRef={menuNodeRef}
        side="right"
        align="center"
        gap={4}
        id={submenuId}
        className="model-lane__submenu"
        role="menu"
        nodeRef={submenuNodeRef}
        keepOpenRefs={[menuNodeRef]}
        onPointerEnter={cancelClose}
        onPointerLeave={scheduleClose}
        onDismiss={() => setContextOpen(false)}
        onEscape={() => setContextOpen(false)}
      >
        {CONTEXT_LENGTH_KEYS.map(([value, key]) => (
          <button
            key={value}
            type="button"
            role="menuitemradio"
            aria-checked={contextLength === value}
            className={`kimi-dd__item model-lane__option${
              contextLength === value ? ' is-selected' : ''
            }`}
            onClick={() => {
              onContextLengthChange(value);
              setContextOpen(false);
              setOpen(false);
            }}
          >
            <span className="kimi-dd__item-text">
              <span className="kimi-dd__item-label">{t(key)}</span>
            </span>
            {contextLength === value ? <IconCheck size={18} className="model-lane__check" /> : null}
          </button>
        ))}
      </PopoverSurface>
    </div>
  );
}
