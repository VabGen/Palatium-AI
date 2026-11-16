import { useState } from 'react';
import toast from 'react-hot-toast';
import { IconBrain, IconChevronDown, IconLoader } from '../icons/kimiStroke';
import {
  requestMemoryClear,
  requestMemoryExtract,
  requestMemoryForget,
  requestMemorySave,
} from '../api/client';
import { t } from '../i18n';
import type { HITLCardView } from '../types/contentDocument';
import { KimiDialog } from './KimiDialog';

type MemoryActionsProps = {
  threadId: string;
  userId: string;
  orgId: string;
  disabled?: boolean;
  onCardCreated: (card: HITLCardView, label: string) => void;
};

type MemoryMode = 'save' | 'forget' | 'extract' | 'clear';

export function MemoryActions({
  threadId,
  userId,
  orgId,
  disabled = false,
  onCardCreated,
}: MemoryActionsProps) {
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<MemoryMode>('save');
  const [entryKey, setEntryKey] = useState('');
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);

  async function runClear() {
    const card = await requestMemoryClear({ thread_id: threadId }, userId, orgId);
    onCardCreated(card, t('memory.label.clear'));
    toast.success(t('memory.toast.cardCreated'));
  }

  async function submit() {
    if (busy || disabled) return;
    if (mode === 'clear') {
      setClearConfirmOpen(true);
      return;
    }
    setBusy(true);
    try {
      let card: HITLCardView;
      let label: string;
      if (mode === 'save') {
        const key = entryKey.trim();
        const body = text.trim();
        if (!key || !body) {
          toast.error(t('memory.error.entryKeyAndText'));
          return;
        }
        card = await requestMemorySave(
          {
            thread_id: threadId,
            entry_key: key,
            text: body,
            namespace_kind: 'user',
            scope_id: userId,
            memory_type: 'preference',
          },
          userId,
          orgId
        );
        label = t('memory.label.save');
      } else if (mode === 'forget') {
        const key = entryKey.trim();
        if (!key) {
          toast.error(t('memory.error.entryKey'));
          return;
        }
        card = await requestMemoryForget(
          {
            thread_id: threadId,
            entry_key: key,
            namespace_kind: 'user',
            scope_id: userId,
          },
          userId,
          orgId
        );
        label = t('memory.label.forget');
      } else {
        card = await requestMemoryExtract({ thread_id: threadId }, userId, orgId);
        label = t('memory.label.extract');
      }
      onCardCreated(card, label);
      setText('');
      if (mode !== 'extract') setEntryKey('');
      toast.success(t('memory.toast.cardCreated'));
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      toast.error(detail.slice(0, 180) || t('memory.error.requestFailed'));
    } finally {
      setBusy(false);
    }
  }

  async function confirmClear() {
    if (busy || disabled) return;
    setBusy(true);
    setClearConfirmOpen(false);
    try {
      await runClear();
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      toast.error(detail.slice(0, 180) || t('memory.error.requestFailed'));
    } finally {
      setBusy(false);
    }
  }

  const submitLabel =
    mode === 'save'
      ? t('memory.submit.save')
      : mode === 'forget'
        ? t('memory.submit.forget')
        : mode === 'extract'
          ? t('memory.submit.extract')
          : t('memory.submit.clear');

  return (
    <div className={`memory-actions${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="memory-toggle"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen(prev => !prev)}
      >
        <IconBrain size={14} />
        <span>{t('memory.toggle')}</span>
        <IconChevronDown size={13} className="memory-chevron" />
      </button>

      {open && (
        <div className="memory-panel" role="group" aria-label={t('memory.panelLabel')}>
          <div className="memory-modes" role="tablist" aria-label={t('memory.modesLabel')}>
            {(
              [
                ['save', t('memory.mode.save')],
                ['forget', t('memory.mode.forget')],
                ['extract', t('memory.mode.extract')],
                ['clear', t('memory.mode.clear')],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={mode === id}
                className={`memory-mode${mode === id ? ' is-active' : ''}${
                  id === 'clear' ? ' memory-mode--danger' : ''
                }`}
                disabled={busy || disabled}
                onClick={() => setMode(id)}
              >
                {label}
              </button>
            ))}
          </div>

          {mode !== 'extract' && mode !== 'clear' && (
            <input
              className="memory-input"
              value={entryKey}
              onChange={e => setEntryKey(e.target.value)}
              placeholder={t('memory.entryKeyPlaceholder')}
              disabled={busy || disabled}
              maxLength={256}
            />
          )}
          {mode === 'save' && (
            <textarea
              className="memory-textarea"
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder={t('memory.textPlaceholder')}
              rows={2}
              disabled={busy || disabled}
              maxLength={2000}
            />
          )}
          {mode === 'extract' && <p className="memory-hint">{t('memory.extractHint')}</p>}
          {mode === 'clear' && <p className="memory-hint memory-hint--danger">{t('memory.clearHint')}</p>}

          <button
            type="button"
            className={`memory-submit${mode === 'clear' ? ' memory-submit--danger' : ''}`}
            disabled={busy || disabled}
            onClick={() => void submit()}
          >
            {busy ? <IconLoader className="spin" size={14} /> : null}
            <span>{submitLabel}</span>
          </button>
        </div>
      )}

      <KimiDialog
        open={clearConfirmOpen}
        title={t('memory.clearConfirm.title')}
        description={t('memory.clearConfirm.description')}
        closeLabel={t('memory.clearConfirm.cancel')}
        onClose={() => setClearConfirmOpen(false)}
        footer={
          <>
            <button
              type="button"
              className="kimi-btn kimi-btn--ghost"
              disabled={busy}
              onClick={() => setClearConfirmOpen(false)}
            >
              {t('memory.clearConfirm.cancel')}
            </button>
            <button
              type="button"
              className="kimi-btn kimi-btn--danger"
              disabled={busy}
              data-autofocus
              onClick={() => void confirmClear()}
            >
              {busy ? <IconLoader className="spin" size={14} /> : null}
              <span>{t('memory.clearConfirm.confirm')}</span>
            </button>
          </>
        }
      />
    </div>
  );
}
