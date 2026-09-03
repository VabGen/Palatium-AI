import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import {
  Copy,
  Download,
  LoaderCircle,
  RotateCw,
  SendHorizontal,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from 'lucide-react';
import {
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
import { BlockRenderer } from './BlockRenderer';
import { HitlCards } from './HitlCards';
import { MemoryActions } from './MemoryActions';

const THREAD_STORAGE_KEY = 'palatium.thread_id';
const USER_STORAGE_KEY = 'palatium.user_id';
const ORG_STORAGE_KEY = 'palatium.org_id';

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

type ChatMessage = { id: string; role: 'user'; text: string } | AssistantChatMessage;

function newThreadId(): string {
  return `thread-${crypto.randomUUID()}`;
}

function resolveThreadId(): string {
  try {
    const stored = window.localStorage.getItem(THREAD_STORAGE_KEY);
    if (stored && stored.startsWith('thread-')) return stored;
  } catch {}
  const created = newThreadId();
  try {
    window.localStorage.setItem(THREAD_STORAGE_KEY, created);
  } catch {}
  return created;
}

function resolveUserId(): string {
  try {
    const stored = window.localStorage.getItem(USER_STORAGE_KEY);
    if (stored && stored.startsWith('user-')) return stored;
  } catch {}
  const created = `user-${crypto.randomUUID()}`;
  try {
    window.localStorage.setItem(USER_STORAGE_KEY, created);
  } catch {}
  return created;
}

function resolveOrgId(): string {
  try {
    const stored = window.localStorage.getItem(ORG_STORAGE_KEY);
    if (stored && stored.startsWith('org-')) return stored;
  } catch {}
  return 'org-default';
}

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
  const [threadId] = useState(resolveThreadId);
  const [userId] = useState(resolveUserId);
  const [orgId] = useState(resolveOrgId);
  const [input, setInput] = useState('');
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const [devMode, setDevMode] = useState(false);
  const [wsConnected, setWsConnected] = useState(false);
  const messageEndRef = useRef<HTMLDivElement>(null);

  const canSend = useMemo(() => input.trim().length > 0 && !busy, [input, busy]);

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
          const hasHitl = hydratedCards.some(card => card.status === 'pending');
          restored.push({
            id: turn.id ?? crypto.randomUUID(),
            role: 'assistant',
            document,
            hitlCards: hydratedCards,
            _requiresReview: requiresReview,
            _pendingReview: requiresReview && !document && !hasHitl,
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
        toast.success('Продолжаем после вашего выбора');
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
    if (!text || busy) return;
    setInput('');
    setBusy(true);
    const userMsgId = crypto.randomUUID();
    setMessages(prev => [...prev, { id: userMsgId, role: 'user', text }]);

    try {
      const result = await processIntent(text, threadId, userId, orgId);
      const hydratedCards = await hydratePendingHitlCards(
        fieldsFromFormatterResult(result).hitlCards,
        userId,
        orgId
      );
      const assistant = buildAssistantMessage({ ...result, hitl_cards: hydratedCards });
      setMessages(prev => [...prev, assistant]);
    } catch (err) {
      setMessages(prev => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          document: null,
          hitlCards: [],
          _requiresReview: false,
          _pendingReview: false,
          error: err instanceof Error ? err.message : 'Request failed',
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
        const result = await processIntent(userMsg.text, threadId, userId, orgId);
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
        toast.success('Ответ обновлён');
      } catch (err) {
        setMessages(prev =>
          prev.map(msg =>
            msg.id === messageId && msg.role === 'assistant'
              ? {
                  ...msg,
                  error: err instanceof Error ? err.message : 'Ошибка при регенерации',
                  _regenerating: false,
                }
              : msg
          )
        );
        toast.error('Не удалось обновить ответ');
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
        toast.error('Не удалось отправить отзыв на сервер, но он сохранён локально');
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

  const startNewThread = useCallback(() => {
    const next = newThreadId();
    try {
      window.localStorage.setItem(THREAD_STORAGE_KEY, next);
    } catch {}
    window.location.reload();
  }, []);

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="brand">
          <Sparkles size={18} className="brand-mark" />
          <div>
            <h1>Palatium</h1>
            <p>Structured agent replies</p>
            {devMode && <span className="dev-badge">🔧 DEV</span>}
            {wsConnected && <span className="dev-badge">WS</span>}
          </div>
        </div>
        <div className="header-actions">
          <button type="button" className="toolbar-btn" onClick={startNewThread}>
            New chat
          </button>
          <span className="thread-pill">{threadId.slice(0, 18)}…</span>
        </div>
      </header>

      <main className="transcript">
        {hydrated && messages.length === 0 && (
          <div className="empty">
            <h2>Ask anything</h2>
            <p>I'll provide structured answers. You can copy, export, or give feedback.</p>
            <div className="suggestions">
              {['Какие планы на сегодня', 'Составь план встречи на завтра'].map(hint => (
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
                ) : message._pendingReview ? (
                  <div className="msg pending-review">
                    <LoaderCircle className="spin" size={18} />
                    <span>Ответ проверяется модератором…</span>
                  </div>
                ) : message.document ? (
                  <>
                    <BlockRenderer document={message.document} />
                    {showDevGap && (
                      <p className="hitl-dev-gap">
                        DEV: document looks like an exclusive menu but no HITL cards were minted.
                      </p>
                    )}
                    {message.error && <p className="msg-error">{message.error}</p>}
                    <div className="msg-actions">
                      <button
                        className={`action-btn ${message._feedbackLike ? 'active' : ''}`}
                        onClick={() => handleFeedback(message.id, 'like')}
                        disabled={message._feedbackSending || busy}
                        aria-pressed={!!message._feedbackLike}
                        aria-label="Like this response"
                      >
                        <ThumbsUp size={16} />
                      </button>
                      <button
                        className={`action-btn ${message._feedbackDislike ? 'active' : ''}`}
                        onClick={() => handleFeedback(message.id, 'dislike')}
                        disabled={message._feedbackSending || busy}
                        aria-pressed={!!message._feedbackDislike}
                        aria-label="Dislike this response"
                      >
                        <ThumbsDown size={16} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={() => copyMessageContent(message)}
                        disabled={busy}
                        aria-label="Copy response text"
                      >
                        <Copy size={16} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={() => {
                          if (!message.document) return;
                          void downloadDocumentPdf(message.document, threadId, userId, orgId).catch(
                            (err: unknown) => {
                              toast.error('PDF export failed');
                              console.error(err);
                            }
                          );
                        }}
                        disabled={busy}
                        aria-label="Export as PDF"
                      >
                        <Download size={16} />
                      </button>
                      <button
                        className="action-btn"
                        onClick={() => regenerateResponse(message.id)}
                        disabled={busy || message._regenerating}
                        aria-label="Regenerate response"
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
                  <p className="msg-error">{message.error ?? 'Empty response'}</p>
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
            <span>Agents working</span>
          </div>
        )}
        <div ref={messageEndRef} />
      </main>

      <div className="composer-stack">
        <MemoryActions
          threadId={threadId}
          userId={userId}
          orgId={orgId}
          disabled={busy}
          onCardCreated={handleMemoryCardCreated}
        />
        <form
          className="composer"
          onSubmit={e => {
            e.preventDefault();
            void send();
          }}
        >
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            placeholder="Message Palatium…"
            rows={2}
            onKeyDown={e => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <button
            type="submit"
            disabled={!canSend}
            className={`send-btn ${busy ? 'sending' : ''}`}
            aria-label="Send message"
          >
            {busy ? <LoaderCircle className="spin" size={18} /> : <SendHorizontal size={18} />}
          </button>
        </form>
      </div>
    </div>
  );
}
