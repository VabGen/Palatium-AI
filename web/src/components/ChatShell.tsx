import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import {
  ChevronDown,
  Copy,
  Download,
  FileText,
  LoaderCircle,
  Paperclip,
  RotateCw,
  SendHorizontal,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
  X,
} from 'lucide-react';
import {
  INTENT_TEXT_LIMIT,
  deleteAttachment,
  downloadDocumentPdf,
  ensureAccessToken,
  fetchDialogTurns,
  processIntent,
  sendFeedback,
} from '../api/client';
import type { ContentDocument, FormatterTaskResult, HITLCardView } from '../types/contentDocument';
import { fieldsFromFormatterResult, hydratePendingHitlCards } from '../lib/hitl';
import { looksLikeExclusiveMenu } from '../lib/exclusiveMenu';
import { connectSessionSocket, startSessionSocketPing } from '../lib/sessionSocket';
import { formatNumber, t } from '../i18n';
import { setPanelOpen, startNewThread as startNewThreadInRuntime } from '../runtime/store';
import { useAssistantRuntime } from '../runtime/useRuntime';
import {
  ATTACHMENT_ACCEPT,
  MAX_ATTACHMENTS_PER_TURN,
  MAX_ATTACHMENT_LABEL,
  attachmentRefusalReason,
  formatAttachmentSize,
  refusalLabel,
  uploadAttachment,
} from '../lib/attachments';
import type { AttachmentDraft } from '../lib/attachments';
import { BlockRenderer } from './BlockRenderer';
import { HitlCards } from './HitlCards';
import { MemoryActions } from './MemoryActions';

/**
 * Порог, за которым счётчик символов начинает подсвечиваться предупреждающе.
 */
const COUNTER_WARN_THRESHOLD = 2_000;

type AssistantChatMessage = {
  id: string;
  role: 'assistant';
  document: ContentDocument | null;
  hitlCards?: HITLCardView[];
  _requiresReview?: boolean;
  _pendingReview?: boolean;
  _feedbackLike?: boolean;
  _feedbackDislike?: boolean;
  _feedbackSending?: boolean;
  _regenerating?: boolean;
  error?: string;
  status?: string;
};

type ChatMessage =
  | {
      id: string;
      role: 'user';
      text: string;
      /** Ids actually injected into that turn, so a regenerate repeats the same context. */
      attachmentIds?: string[];
      attachmentNames?: string[];
    }
  | AssistantChatMessage;

function isContentDocument(value: unknown): value is ContentDocument {
  return (
    typeof value === 'object' &&
    value !== null &&
    'schema_version' in value &&
    'blocks' in value &&
    Array.isArray((value as ContentDocument).blocks)
  );
}

function isHitlCardView(value: unknown): value is HITLCardView {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as HITLCardView).card_id === 'string' &&
    Array.isArray((value as HITLCardView).options)
  );
}

function textAsDocument(text: string): ContentDocument {
  return {
    schema_version: 1,
    locale: 'ru-RU',
    title: '',
    blocks: [{ type: 'paragraph', text }],
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
      interaction: 'none',
    },
  };
}

function parseAssistantPayload(
  payload: unknown,
  fallbackText: string
): { document: ContentDocument; requiresReview: boolean; hitlCards: HITLCardView[] } {
  if (payload && typeof payload === 'object') {
    const record = payload as Record<string, unknown>;
    const requiresReview = Boolean(record.requires_review) || false;
    const rawCards = Array.isArray(record.hitl_cards)
      ? record.hitl_cards.filter(isHitlCardView)
      : [];
    if (isContentDocument(record.document)) {
      return { document: record.document, requiresReview, hitlCards: rawCards };
    }
    if (isContentDocument(payload)) {
      return { document: payload, requiresReview, hitlCards: rawCards };
    }
  }
  return { document: textAsDocument(fallbackText), requiresReview: false, hitlCards: [] };
}

function getDocumentPlainText(doc: ContentDocument): string {
  const parts: string[] = [];
  if (doc.title) parts.push(doc.title);
  for (const block of doc.blocks) {
    switch (block.type) {
      case 'heading':
      case 'paragraph':
      case 'callout':
        if ('text' in block && block.text) parts.push(block.text);
        else if ('body' in block && block.body) parts.push(block.body);
        break;
      case 'code':
        if ('content' in block && block.content) parts.push(block.content);
        break;
      case 'formula':
        if ('latex' in block && block.latex) parts.push(block.latex);
        break;
      case 'widget':
        if ('title' in block && block.title) parts.push(block.title);
        break;
      case 'list':
        for (const item of block.items) {
          if (item.text) parts.push(item.text);
        }
        break;
      case 'steps':
        for (const step of block.items) {
          if (step.title) parts.push(step.title);
          if (step.body) parts.push(step.body);
        }
        break;
      case 'kv':
        for (const kv of block.items) {
          if (kv.label) parts.push(`${kv.label}: ${kv.value}`);
        }
        break;
      case 'table':
        for (const row of block.rows) {
          parts.push(row.join(' | '));
        }
        break;
      case 'chart':
        if (block.title) parts.push(block.title);
        parts.push(block.labels.join(', '));
        break;
      default:
        break;
    }
  }
  return parts.join('\n').trim() || '(empty)';
}

function buildAssistantMessage(result: FormatterTaskResult, id?: string): AssistantChatMessage {
  return {
    id: id ?? crypto.randomUUID(),
    role: 'assistant',
    ...fieldsFromFormatterResult(result),
  };
}

export function ChatShell() {
  // Идентификаторы приходят из runtime: в embed — из SedContext (`user.id`,
  // `scope.tenantId`), автономно — из in-memory значений сессии. Storage запрещён.
  const { userId, orgId, threadId, hostStatus, userName } = useAssistantRuntime();
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [devMode, setDevMode] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const [attachments, setAttachments] = useState<AttachmentDraft[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const messageEndRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const uploading = attachments.some(chip => chip.status === 'uploading');

  // ── Лимит символов ───────────────────────────────────────────────────────
  const inputLength = input.length;
  const inputRemaining = INTENT_TEXT_LIMIT - inputLength;
  const overLimit = inputRemaining < 0;
  const nearLimit = !overLimit && inputRemaining <= COUNTER_WARN_THRESHOLD;

  const canSend = useMemo(
    () => input.trim().length > 0 && !busy && !uploading && !overLimit,
    [input, busy, uploading, overLimit]
  );

  const addFiles = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const slots = MAX_ATTACHMENTS_PER_TURN - attachments.length;
      if (slots <= 0) {
        toast.error(t('toast.tooManyFiles', { count: MAX_ATTACHMENTS_PER_TURN }));
        return;
      }
      if (files.length > slots) {
        toast.error(t('toast.tooManyFiles', { count: MAX_ATTACHMENTS_PER_TURN }));
      }

      for (const file of files.slice(0, slots)) {
        const refusal = attachmentRefusalReason(file);
        if (refusal) {
          toast.error(`${file.name}: ${refusal}`);
          continue;
        }

        const localId = crypto.randomUUID();
        setAttachments(prev => [
          ...prev,
          {
            localId,
            filename: file.name,
            sizeBytes: file.size,
            status: 'uploading',
          },
        ]);

        void (async () => {
          try {
            const stored = await uploadAttachment(file, { threadId, userId, orgId });
            // A refused file still exists as a row: it is shown with its reason
            // instead of vanishing, so the user learns *why* it never reached a turn.
            const failure = refusalLabel(stored);
            setAttachments(prev =>
              prev.map(chip =>
                chip.localId === localId
                  ? {
                      ...chip,
                      serverId: stored.attachment_id,
                      status: failure ? 'failed' : 'ready',
                      error: failure ?? undefined,
                    }
                  : chip
              )
            );
            if (failure) toast.error(`${stored.filename}: ${failure}`);
          } catch (err) {
            const message = err instanceof Error ? err.message : t('toast.uploadFailed');
            setAttachments(prev =>
              prev.map(chip =>
                chip.localId === localId ? { ...chip, status: 'failed', error: message } : chip
              )
            );
            toast.error(`${file.name}: ${message.slice(0, 160)}`);
          }
        })();
      }
    },
    [attachments.length, threadId, userId, orgId]
  );

  const removeAttachment = useCallback(
    (localId: string) => {
      const chip = attachments.find(item => item.localId === localId);
      if (chip?.serverId) {
        // Best effort: rows carry a TTL and a sweep reclaims them, so a failed
        // delete must never block the composer (060).
        void deleteAttachment(chip.serverId, userId, orgId).catch(() => {
          toast.error(t('toast.deleteFailed'));
        });
      }
      setAttachments(prev => prev.filter(item => item.localId !== localId));
    },
    [attachments, userId, orgId]
  );

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'D') {
        e.preventDefault();
        setDevMode(prev => !prev);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  useEffect(() => {
    let cancelled = false;
    let socket: WebSocket | null = null;
    let stopPing: (() => void) | null = null;

    void (async () => {
      try {
        const token = await ensureAccessToken(userId, orgId);
        if (cancelled) return;
        socket = connectSessionSocket(threadId, token, {
          onSubscribed: () => setWsConnected(true),
          onError: () => setWsConnected(false),
        });
        stopPing = startSessionSocketPing(socket);
      } catch {
        setWsConnected(false);
      }
    })();

    return () => {
      cancelled = true;
      stopPing?.();
      socket?.close();
      setWsConnected(false);
    };
  }, [threadId, userId, orgId]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const turns = await fetchDialogTurns(threadId, 50, userId, orgId);
        if (cancelled || turns.length === 0) {
          setHydrated(true);
          return;
        }
        const restored: ChatMessage[] = [];
        for (const turn of turns) {
          if (turn.role === 'user') {
            restored.push({
              id: turn.id ?? crypto.randomUUID(),
              role: 'user',
              text: turn.content,
            });
            continue;
          }
          const { document, requiresReview, hitlCards } = parseAssistantPayload(
            turn.payload,
            turn.content
          );
          const hydratedCards = await hydratePendingHitlCards(hitlCards, userId, orgId);
          const feedback = (turn.payload as { feedback?: { like?: boolean; dislike?: boolean } })
            ?.feedback;
          restored.push({
            id: turn.id ?? crypto.randomUUID(),
            role: 'assistant',
            document,
            hitlCards: hydratedCards,
            _requiresReview: requiresReview,
            _pendingReview: false,
            _feedbackLike: feedback?.like || false,
            _feedbackDislike: feedback?.dislike || false,
            status: 'success',
            error: undefined,
          });
        }
        if (!cancelled) setMessages(restored);
      } catch (err) {
        console.warn('Session hydrate failed:', err);
      } finally {
        if (!cancelled) setHydrated(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, userId, orgId]);

  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, busy]);

  const handleHitlResolved = useCallback(
    (messageId: string, card: HITLCardView, resumed?: FormatterTaskResult | null) => {
      setMessages(prev =>
        prev.map(msg => {
          if (msg.id !== messageId || msg.role !== 'assistant') return msg;
          const hitlCards = (msg.hitlCards ?? [])
            .map(existing => (existing.card_id === card.card_id ? card : existing))
            .filter(existing => existing.status === 'pending');
          if (resumed?.output) {
            return {
              ...msg,
              document: resumed.output,
              hitlCards,
              _pendingReview: false,
              _requiresReview: resumed.requires_review,
              status: resumed.status,
              error: resumed.error ?? undefined,
            };
          }
          return {
            ...msg,
            hitlCards,
            _pendingReview: hitlCards.length > 0 ? false : msg._pendingReview,
          };
        })
      );
      if (resumed?.output) {
        toast.success(t('toast.resuming'));
      }
    },
    []
  );

  const handleMemoryCardCreated = useCallback(
    (card: HITLCardView, label: string) => {
      void (async () => {
        const hydrated = await hydratePendingHitlCards([card], userId, orgId);
        setMessages(prev => [
          ...prev,
          {
            id: crypto.randomUUID(),
            role: 'assistant',
            document: textAsDocument(label),
            hitlCards: hydrated,
            _requiresReview: true,
            _pendingReview: false,
            status: 'partial',
          },
        ]);
      })();
    },
    [userId, orgId]
  );

  async function send() {
    const text = input.trim();
    if (!text || busy || uploading) return;

    // Дублируем клиентскую валидацию из `processIntent` — здесь она защищает
    // от случайного сабмита по Enter при вставке слишком длинного текста.
    if (input.length > INTENT_TEXT_LIMIT) {
      toast.error(
        t('error.messageTooLong', {
          used: formatNumber(input.length),
          limit: formatNumber(INTENT_TEXT_LIMIT),
        })
      );
      return;
    }

    const outgoing = attachments.filter(chip => chip.status === 'ready' && chip.serverId);
    const attachmentIds = outgoing.map(chip => chip.serverId as string);
    const attachmentNames = outgoing.map(chip => chip.filename);
    setInput('');
    setBusy(true);
    // Файлы уже уехали в этот ход: снимаем чипы, иначе тот же файл молча ушёл бы
    // ещё раз со следующим сообщением. Неудачные оставляем — их причину надо видеть.
    setAttachments(prev => prev.filter(chip => chip.status !== 'ready'));
    const userMsgId = crypto.randomUUID();
    setMessages(prev => [
      ...prev,
      { id: userMsgId, role: 'user', text, attachmentIds, attachmentNames },
    ]);

    try {
      const result = await processIntent(text, threadId, userId, orgId, attachmentIds);
      const hydratedCards = await hydratePendingHitlCards(
        fieldsFromFormatterResult(result).hitlCards,
        userId,
        orgId
      );
      const assistant = buildAssistantMessage({ ...result, hitl_cards: hydratedCards });
      setMessages(prev => [...prev, assistant]);
    } catch (err) {
      // Сообщение уже humanized в `errorDetail` (см. client.ts).
      const message = err instanceof Error ? err.message : t('error.requestFailed');
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          document: null,
          hitlCards: [],
          _requiresReview: false,
          _pendingReview: false,
          error: message,
          status: 'failure',
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  const regenerateResponse = useCallback(
    async (messageId: string) => {
      const target = messages.find(m => m.id === messageId && m.role === 'assistant');
      if (!target) return;
      const idx = messages.indexOf(target);
      const userMsg = messages
        .slice(0, idx)
        .reverse()
        .find(m => m.role === 'user');
      if (!userMsg || userMsg.role !== 'user') return;

      setMessages(prev =>
        prev.map(msg =>
          msg.id === messageId && msg.role === 'assistant' ? { ...msg, _regenerating: true } : msg
        )
      );
      setBusy(true);
      try {
        const result = await processIntent(
          userMsg.text,
          threadId,
          userId,
          orgId,
          userMsg.attachmentIds ?? []
        );
        const hydratedCards = await hydratePendingHitlCards(
          fieldsFromFormatterResult(result).hitlCards,
          userId,
          orgId
        );
        const assistant = buildAssistantMessage(
          { ...result, hitl_cards: hydratedCards },
          messageId
        );
        setMessages(prev =>
          prev.map(msg => (msg.id === messageId && msg.role === 'assistant' ? assistant : msg))
        );
        toast.success(t('toast.regenerated'));
      } catch (err) {
        setMessages(prev =>
          prev.map(msg =>
            msg.id === messageId && msg.role === 'assistant'
              ? {
                  ...msg,
                  error: err instanceof Error ? err.message : t('toast.regenerateFailed'),
                  _regenerating: false,
                }
              : msg
          )
        );
        toast.error(t('toast.regenerateFailed'));
      } finally {
        setBusy(false);
      }
    },
    [messages, threadId, userId, orgId]
  );

  const handleFeedback = useCallback(
    async (messageId: string, type: 'like' | 'dislike') => {
      const message = messages.find(m => m.id === messageId);
      if (!message || message.role !== 'assistant') return;
      if (message._feedbackSending) return;

      const isLike = type === 'like';
      const isCurrentlyActive = isLike ? message._feedbackLike : message._feedbackDislike;
      const newActive = !isCurrentlyActive;

      setMessages(prev =>
        prev.map(msg => {
          if (msg.id !== messageId || msg.role !== 'assistant') return msg;
          return {
            ...msg,
            _feedbackLike: isLike ? newActive : false,
            _feedbackDislike: isLike ? false : newActive,
            _feedbackSending: true,
          };
        })
      );

      try {
        await sendFeedback(messageId, type, userId, orgId);
        setMessages(prev =>
          prev.map(msg => {
            if (msg.id !== messageId || msg.role !== 'assistant') return msg;
            return { ...msg, _feedbackSending: false };
          })
        );
      } catch (err) {
        console.warn('Feedback not saved on server:', err);
        setMessages(prev =>
          prev.map(msg => {
            if (msg.id !== messageId || msg.role !== 'assistant') return msg;
            return { ...msg, _feedbackSending: false };
          })
        );
        toast.error(t('toast.feedbackFailed'));
      }
    },
    [messages, userId, orgId]
  );

  const copyMessageContent = useCallback((message: ChatMessage) => {
    if (message.role !== 'assistant' || !message.document) return;
    const text = getDocumentPlainText(message.document);
    if (text) {
      navigator.clipboard.writeText(text).catch(() => {});
    }
  }, []);

  // Никакого `window.location.reload()`: виджет встроен в страницу СЭД и не имеет
  // права её перезагружать. Новый тред = сброс состояния в памяти + новый threadId.
  const handleNewThread = useCallback(() => {
    startNewThreadInRuntime();
    setMessages([]);
    setAttachments([]);
    setHydrated(false);
  }, []);

  // ── Counter class (для CSS) ──────────────────────────────────────────────
  const counterClass = overLimit
    ? 'composer-counter composer-counter--over'
    : nearLimit
      ? 'composer-counter composer-counter--warn'
      : 'composer-counter';

  // Screen readers announce only at warn/over thresholds, not on every keystroke.
  const counterLive: 'polite' | 'off' = overLimit || nearLimit ? 'polite' : 'off';

  return (
    <div className="shell" part="shell">
      <header className="shell-header" part="header">
        <div className="brand">
          <Sparkles size={18} className="brand-mark" />
          <div>
            <h1>{t('app.title')}</h1>
            <p>{t('app.tagline')}</p>
            {devMode && <span className="dev-badge">🔧 {t('badge.dev')}</span>}
            {wsConnected && <span className="dev-badge">{t('badge.ws')}</span>}
            {hostStatus === 'standalone' && (
              <span className="dev-badge">{t('badge.standalone')}</span>
            )}
          </div>
        </div>
        <div className="header-actions">
          <button type="button" className="toolbar-btn" onClick={handleNewThread}>
            {t('header.newChat')}
          </button>
          <span className="thread-pill">{threadId.slice(0, 18)}…</span>
          <button
            type="button"
            className="toolbar-btn"
            part="close"
            onClick={() => setPanelOpen(false)}
            aria-label={t('header.collapse')}
            title={t('header.collapse')}
          >
            <ChevronDown size={16} aria-hidden />
          </button>
        </div>
      </header>

      <main className="transcript" part="transcript">
        {hydrated && messages.length === 0 && (
          <div className="empty">
            {userName && (
              <p className="empty-greeting">{t('empty.greeting', { name: userName })}</p>
            )}
            <h2>{t('empty.title')}</h2>
            <p>{t('empty.body')}</p>
            <p className="empty-hint">
              {t('empty.attachmentsHint', { size: MAX_ATTACHMENT_LABEL })}
            </p>
            <div className="suggestions">
              {[t('empty.suggestion.0'), t('empty.suggestion.1')].map(hint => (
                <button
                  key={hint}
                  type="button"
                  className="suggestion"
                  onClick={() => setInput(hint)}
                >
                  {hint}
                </button>
              ))}
            </div>
          </div>
        )}

        {messages.map(message => {
          if (message.role === 'user') {
            return (
              <div key={message.id} className="msg user fade-in">
                <div className="avatar">U</div>
                <div className="bubble">
                  <p>{message.text}</p>
                  {message.attachmentNames && message.attachmentNames.length > 0 && (
                    <ul className="bubble-attachments">
                      {message.attachmentNames.map(name => (
                        <li key={name}>
                          <Paperclip size={12} />
                          <span>{name}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>
            );
          }

          const pendingHitl = (message.hitlCards ?? []).filter(card => card.status === 'pending');
          const showHitl = pendingHitl.length > 0;
          const showDevGap =
            devMode &&
            !showHitl &&
            looksLikeExclusiveMenu(message.document) &&
            message._requiresReview;

          return (
            <div key={message.id} className="msg assistant fade-in">
              <div className="avatar">P</div>
              <div className="bubble">
                {showHitl ? (
                  <HitlCards
                    cards={pendingHitl}
                    userId={userId}
                    orgId={orgId}
                    onResolved={(card, resumed) => handleHitlResolved(message.id, card, resumed)}
                  />
                ) : message.document ? (
                  <>
                    <BlockRenderer document={message.document} />
                    {showDevGap && <p className="hitl-dev-gap">{t('msg.devGap')}</p>}
                    {message.error && <p className="msg-error">{message.error}</p>}
                    <div className="msg-actions">
                      <button
                        className={`action-btn ${message._feedbackLike ? 'active' : ''}`}
                        onClick={() => handleFeedback(message.id, 'like')}
                        disabled={message._feedbackSending || busy}
                        aria-pressed={!!message._feedbackLike}
                        aria-label={t('action.like')}
                      >
                        <ThumbsUp size={16} />
                      </button>
                      <button
                        className={`action-btn ${message._feedbackDislike ? 'active' : ''}`}
                        onClick={() => handleFeedback(message.id, 'dislike')}
                        disabled={message._feedbackSending || busy}
                        aria-pressed={!!message._feedbackDislike}
                        aria-label={t('action.dislike')}
                      >
                        <ThumbsDown size={16} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={() => copyMessageContent(message)}
                        disabled={busy}
                        aria-label={t('action.copy')}
                      >
                        <Copy size={16} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={() => {
                          if (!message.document) return;
                          void downloadDocumentPdf(message.document, threadId, userId, orgId).catch(
                            (err: unknown) => {
                              toast.error(t('toast.pdfFailed'));
                              console.error(err);
                            }
                          );
                        }}
                        disabled={busy}
                        aria-label={t('action.exportPdf')}
                      >
                        <Download size={16} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={() => regenerateResponse(message.id)}
                        disabled={busy || message._regenerating}
                        aria-label={t('action.regenerate')}
                      >
                        {message._regenerating ? (
                          <LoaderCircle className="spin" size={16} />
                        ) : (
                          <RotateCw size={16} />
                        )}
                      </button>
                      {devMode && message.document && (
                        <span className="dev-meta">
                          Confidence: {message.document.meta.confidence} | Requires review:{' '}
                          {String(message._requiresReview)}
                        </span>
                      )}
                    </div>
                  </>
                ) : (
                  <p className="msg-error">{message.error ?? t('msg.emptyResponse')}</p>
                )}
                {showHitl && message.document && <BlockRenderer document={message.document} />}
              </div>
            </div>
          );
        })}

        {busy && !messages.some(m => m.role === 'assistant' && m._regenerating) && (
          <div className="msg assistant pending fade-in">
            <span className="typing-dots">
              <span>.</span>
              <span>.</span>
              <span>.</span>
            </span>
            <span>{t('msg.agentsWorking')}</span>
          </div>
        )}
        <div ref={messageEndRef} />
      </main>

      <div
        className={`composer-stack${dragActive ? ' is-dragover' : ''}`}
        part="composer"
        onDragOver={e => {
          e.preventDefault();
          setDragActive(true);
        }}
        onDragLeave={() => setDragActive(false)}
        onDrop={e => {
          e.preventDefault();
          setDragActive(false);
          addFiles(Array.from(e.dataTransfer.files));
        }}
      >
        <MemoryActions
          threadId={threadId}
          userId={userId}
          orgId={orgId}
          disabled={busy}
          onCardCreated={handleMemoryCardCreated}
        />
        {attachments.length > 0 && (
          <ul className="attachment-chips" aria-label={t('composer.attachedFiles')}>
            {attachments.map(chip => (
              <li
                key={chip.localId}
                className={`attachment-chip is-${chip.status}`}
                title={chip.error ?? `${chip.filename} (${formatAttachmentSize(chip.sizeBytes)})`}
              >
                {chip.status === 'uploading' ? (
                  <LoaderCircle className="spin" size={13} />
                ) : (
                  <FileText size={13} />
                )}
                <span className="attachment-name">{chip.filename}</span>
                <span className="attachment-size">{formatAttachmentSize(chip.sizeBytes)}</span>
                {chip.status === 'failed' && chip.error && (
                  <span className="attachment-reason">{chip.error}</span>
                )}
                <button
                  type="button"
                  className="attachment-remove"
                  onClick={() => removeAttachment(chip.localId)}
                  aria-label={t('composer.removeAttachment', { name: chip.filename })}
                >
                  <X size={13} />
                </button>
              </li>
            ))}
          </ul>
        )}
        <form
          className="composer"
          onSubmit={e => {
            e.preventDefault();
            void send();
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            accept={ATTACHMENT_ACCEPT}
            onChange={e => {
              addFiles(Array.from(e.target.files ?? []));
              // Reset so picking the same file twice still fires a change event.
              e.target.value = '';
            }}
          />
          <button
            type="button"
            className="attach-btn"
            onClick={() => fileInputRef.current?.click()}
            disabled={busy}
            aria-label={t('composer.attach')}
            title={t('composer.attachTitle', { size: MAX_ATTACHMENT_LABEL })}
          >
            <Paperclip size={18} />
          </button>
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder={t('composer.placeholder')}
            rows={2}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            aria-describedby="composer-counter"
            className={
              overLimit ? 'composer-textarea composer-textarea--over' : 'composer-textarea'
            }
          />
          <button
            type="submit"
            disabled={!canSend}
            className={`send-btn ${busy ? 'sending' : ''}`}
            aria-label={t('composer.send')}
            title={
              overLimit
                ? t('composer.overLimitTitle', {
                    used: formatNumber(inputLength),
                    limit: formatNumber(INTENT_TEXT_LIMIT),
                  })
                : undefined
            }
          >
            {busy ? <LoaderCircle className="spin" size={18} /> : <SendHorizontal size={18} />}
          </button>
        </form>

        {/* Счётчик символов: показывается всегда, когда есть ввод или близко к лимиту */}
        {(inputLength > 0 || nearLimit || overLimit) && (
          <div
            id="composer-counter"
            className={counterClass}
            aria-live={counterLive}
            aria-atomic="true"
          >
            {t('composer.counter', {
              used: formatNumber(inputLength),
              limit: formatNumber(INTENT_TEXT_LIMIT),
            })}
            {overLimit && t('composer.overLimit')}
            {!overLimit && nearLimit && t('composer.nearLimit')}
          </div>
        )}
      </div>
    </div>
  );
}
