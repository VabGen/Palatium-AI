import { useState } from 'react';
import toast from 'react-hot-toast';
import { Brain, ChevronDown, LoaderCircle } from 'lucide-react';
import { requestMemoryConsolidate, requestMemoryForget, requestMemorySave } from '../api/client';
import type { HITLCardView } from '../types/contentDocument';

type MemoryActionsProps = {
  threadId: string;
  userId: string;
  orgId: string;
  disabled?: boolean;
  onCardCreated: (card: HITLCardView, label: string) => void;
};

type MemoryMode = 'save' | 'forget' | 'consolidate';

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
          toast.error('Entry key and text are required');
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
        label = 'Memory save awaiting approval';
      } else if (mode === 'forget') {
        const key = entryKey.trim();
        if (!key) {
          toast.error('Entry key is required');
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
        label = 'Memory forget awaiting approval';
      } else {
        card = await requestMemoryConsolidate({ thread_id: threadId }, userId, orgId);
        label = 'Memory consolidate awaiting approval';
      }
      onCardCreated(card, label);
      setText('');
      if (mode !== 'consolidate') setEntryKey('');
      toast.success('HITL card created');
    } catch (err) {
      const detail = err instanceof Error ? err.message : String(err);
      toast.error(detail.slice(0, 180) || 'Memory request failed');
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
        <span>Memory</span>
        <ChevronDown size={14} className="memory-chevron" />
      </button>

      {open && (
        <div className="memory-panel" role="group" aria-label="Memory HITL actions">
          <div className="memory-modes" role="tablist" aria-label="Memory action">
            {(
              [
                ['save', 'Save'],
                ['forget', 'Forget'],
                ['consolidate', 'Consolidate'],
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

          {mode !== 'consolidate' && (
            <input
              className="memory-input"
              value={entryKey}
              onChange={e => setEntryKey(e.target.value)}
              placeholder="entry_key (e.g. pref-lang)"
              disabled={busy || disabled}
              maxLength={256}
            />
          )}
          {mode === 'save' && (
            <textarea
              className="memory-textarea"
              value={text}
              onChange={e => setText(e.target.value)}
              placeholder="What should be remembered?"
              rows={2}
              disabled={busy || disabled}
              maxLength={2000}
            />
          )}
          {mode === 'consolidate' && (
            <p className="memory-hint">
              Queue sleep-time consolidation for this thread (requires approve).
            </p>
          )}

          <button
            type="button"
            className="memory-submit"
            disabled={busy || disabled}
            onClick={() => void submit()}
          >
            {busy ? <LoaderCircle className="spin" size={14} /> : null}
            <span>
              {mode === 'save'
                ? 'Request save'
                : mode === 'forget'
                  ? 'Request forget'
                  : 'Request consolidate'}
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
