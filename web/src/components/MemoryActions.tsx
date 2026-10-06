import { useState } from 'react';
import toast from 'react-hot-toast';
import { Brain, ChevronDown, LoaderCircle } from 'lucide-react';
import { requestMemoryExtract, requestMemoryForget, requestMemorySave } from '../api/client';
import { t } from '../i18n';
import type { HITLCardView } from '../types/contentDocument';

type MemoryActionsProps = {
  threadId: string;
  userId: string;
  orgId: string;
  disabled?: boolean;
  onCardCreated: (card: HITLCardView, label: string) => void;
};

type MemoryMode = 'save' | 'forget' | 'extract';

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

  async function submit() {
    if (busy || disabled) return;
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

  return (
    <div className={`memory-actions${open ? ' is-open' : ''}`}>
      <button
        type="button"
        className="memory-toggle"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen(prev => !prev)}
      >
        <Brain size={14} />
        <span>{t('memory.toggle')}</span>
        <ChevronDown size={14} className="memory-chevron" />
      </button>

      {open && (
        <div className="memory-panel" role="group" aria-label={t('memory.panelLabel')}>
          <div className="memory-modes" role="tablist" aria-label={t('memory.modesLabel')}>
            {(
              [
                ['save', t('memory.mode.save')],
                ['forget', t('memory.mode.forget')],
                ['extract', t('memory.mode.extract')],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                role="tab"
                aria-selected={mode === id}
                className={`memory-mode${mode === id ? ' is-active' : ''}`}
                disabled={busy || disabled}
                onClick={() => setMode(id)}
              >
                {label}
              </button>
            ))}
          </div>

          {mode !== 'extract' && (
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

          <button
            type="button"
            className="memory-submit"
            disabled={busy || disabled}
            onClick={() => void submit()}
          >
            {busy ? <LoaderCircle className="spin" size={14} /> : null}
            <span>
              {mode === 'save'
                ? t('memory.submit.save')
                : mode === 'forget'
                  ? t('memory.submit.forget')
                  : t('memory.submit.extract')}
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
