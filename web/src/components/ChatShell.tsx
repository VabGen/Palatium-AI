import { useEffect, useMemo, useRef, useState } from "react";
import { Download, LoaderCircle, SendHorizontal, Sparkles } from "lucide-react";
import {
  downloadDocumentPdf,
  fetchDialogTurns,
  fetchHitlCard,
  processIntent,
} from "../api/client";
import type { ContentDocument, FormatterTaskResult, HITLCardView } from "../types/contentDocument";
import { BlockRenderer } from "./BlockRenderer";
import { HitlCards } from "./HitlCards";

const THREAD_STORAGE_KEY = "palatium.thread_id";
const USER_STORAGE_KEY = "palatium.user_id";
const ORG_STORAGE_KEY = "palatium.org_id";

type ChatMessage =
  | { id: string; role: "user"; text: string }
  | {
      id: string;
      role: "assistant";
      document: ContentDocument | null;
      hitlCards: HITLCardView[];
      error?: string;
      status?: string;
    };

function newThreadId(): string {
  return `thread-${crypto.randomUUID()}`;
}

function resolveThreadId(): string {
  try {
    const stored = window.localStorage.getItem(THREAD_STORAGE_KEY);
    if (stored && stored.startsWith("thread-")) {
      return stored;
    }
  } catch {
    /* ignore */
  }
  const created = newThreadId();
  try {
    window.localStorage.setItem(THREAD_STORAGE_KEY, created);
  } catch {
    /* ignore */
  }
  return created;
}

function resolveUserId(): string {
  try {
    const stored = window.localStorage.getItem(USER_STORAGE_KEY);
    if (stored && stored.startsWith("user-")) {
      return stored;
    }
  } catch {
    /* ignore */
  }
  const created = `user-${crypto.randomUUID()}`;
  try {
    window.localStorage.setItem(USER_STORAGE_KEY, created);
  } catch {
    /* ignore */
  }
  return created;
}

function resolveOrgId(): string {
  try {
    const stored = window.localStorage.getItem(ORG_STORAGE_KEY);
    if (stored && stored.startsWith("org-")) {
      return stored;
    }
  } catch {
    /* ignore */
  }
  const created = "org-default";
  try {
    window.localStorage.setItem(ORG_STORAGE_KEY, created);
  } catch {
    /* ignore */
  }
  return created;
}

function isContentDocument(value: unknown): value is ContentDocument {
  return (
    typeof value === "object" &&
    value !== null &&
    "schema_version" in value &&
    "blocks" in value &&
    Array.isArray((value as ContentDocument).blocks)
  );
}

function isHitlCardView(value: unknown): value is HITLCardView {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as HITLCardView).card_id === "string" &&
    Array.isArray((value as HITLCardView).options)
  );
}

function parseAssistantPayload(
  payload: unknown,
  fallbackText: string,
): { document: ContentDocument; hitlCards: HITLCardView[] } {
  if (payload && typeof payload === "object") {
    const record = payload as Record<string, unknown>;
    const envelope =
      record.schema === "assistant_turn_v1" ||
      ("document" in record && "hitl_cards" in record);
    if (envelope) {
      return {
        document: isContentDocument(record.document)
          ? record.document
          : textAsDocument(fallbackText),
        hitlCards: Array.isArray(record.hitl_cards)
          ? record.hitl_cards.filter(isHitlCardView)
          : [],
      };
    }
    if (isContentDocument(payload)) {
      return { document: payload, hitlCards: [] };
    }
  }
  return { document: textAsDocument(fallbackText), hitlCards: [] };
}

function textAsDocument(text: string): ContentDocument {
  return {
    schema_version: 1,
    locale: "ru-RU",
    title: "",
    blocks: [{ type: "paragraph", text }],
    actions: [],
    meta: {
      confidence: 1,
      requires_review: false,
      source_refs: [],
    },
  };
}

export function ChatShell() {
  const [threadId] = useState(resolveThreadId);
  const [userId] = useState(resolveUserId);
  const [orgId] = useState(resolveOrgId);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [hydrated, setHydrated] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  const canSend = useMemo(
    () => input.trim().length > 0 && !busy,
    [input, busy],
  );

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const turns = await fetchDialogTurns(threadId, 50, userId, orgId);
        if (cancelled || turns.length === 0) {
          return;
        }
        const restored: ChatMessage[] = await Promise.all(
          turns.map(async (turn) => {
            if (turn.role === "user") {
              return {
                id: turn.id ?? crypto.randomUUID(),
                role: "user" as const,
                text: turn.content,
              };
            }
            const { document, hitlCards } = parseAssistantPayload(
              turn.payload,
              turn.content,
            );
            const refreshed = (
              await Promise.all(
                hitlCards.map(async (card) => {
                  // Pending-only interactive hydrate; never keep payload secrets as fallback.
                  if (card.status !== "pending") {
                    return null;
                  }
                  try {
                    const live = await fetchHitlCard(card.card_id, userId, orgId);
                    return live.status === "pending" ? live : null;
                  } catch {
                    return null;
                  }
                }),
              )
            ).filter((card): card is HITLCardView => card !== null);
            return {
              id: turn.id ?? crypto.randomUUID(),
              role: "assistant" as const,
              document,
              hitlCards: refreshed,
              status: "success",
            };
          }),
        );
        setMessages(restored);
      } catch {
        /* empty transcript on hydrate failure */
      } finally {
        if (!cancelled) {
          setHydrated(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [threadId, userId, orgId]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  async function send() {
    const text = input.trim();
    if (!text || busy) return;
    setInput("");
    setBusy(true);
    const messageId = crypto.randomUUID();
    setMessages((prev) => [...prev, { id: messageId, role: "user", text }]);

    try {
      const result = await processIntent(text, threadId, userId, orgId);
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          document: result.output,
          hitlCards: (result.hitl_cards ?? []).filter((c) => c.status === "pending"),
          error: result.error ?? undefined,
          status: result.status,
        },
      ]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          document: null,
          hitlCards: [],
          error: err instanceof Error ? err.message : "Request failed",
          status: "failure",
        },
      ]);
    } finally {
      setBusy(false);
    }
  }

  function onHitlResolved(
    messageId: string,
    card: HITLCardView,
    resumed?: FormatterTaskResult | null,
  ) {
    setMessages((prev) =>
      prev.map((message) => {
        if (message.id !== messageId || message.role !== "assistant") {
          return message;
        }
        return {
          ...message,
          hitlCards: message.hitlCards.map((item) =>
            item.card_id === card.card_id ? card : item,
          ),
        };
      }),
    );
    if (resumed?.output) {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          document: resumed.output,
          hitlCards: (resumed.hitl_cards ?? []).filter((c) => c.status === "pending"),
          status: resumed.status,
          error: resumed.error ?? undefined,
        },
      ]);
    }
    // Quality reject returns resumed revision; approve only updates card status above.
  }

  function startNewThread() {
    const next = newThreadId();
    try {
      window.localStorage.setItem(THREAD_STORAGE_KEY, next);
    } catch {
      /* ignore */
    }
    window.location.reload();
  }

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="brand">
          <Sparkles size={18} className="brand-mark" />
          <div>
            <h1>Palatium</h1>
            <p>Structured agent replies</p>
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
        {hydrated && messages.length === 0 ? (
          <div className="empty">
            <h2>Ask anything</h2>
            <p>
              Responses 🎶🎶🎶
            </p>
            <div className="suggestions">
              {[
                "Какие планы на сегодня",
                "Составь план встречи на завтра",
              ].map((hint) => (
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
        ) : null}

        {messages.map((message) =>
          message.role === "user" ? (
            <div key={message.id} className="msg user">
              <p>{message.text}</p>
            </div>
          ) : (
            <div key={message.id} className="msg assistant">
              {message.document ? (
                <>
                  <BlockRenderer document={message.document} />
                  <div className="msg-toolbar">
                    <button
                      type="button"
                      className="toolbar-btn"
                      onClick={() => {
                        if (!message.document) return;
                        void downloadDocumentPdf(message.document, threadId, userId, orgId).catch((err: unknown) => {
                          window.alert(
                            err instanceof Error ? err.message : "PDF export failed",
                          );
                        });
                      }}
                    >
                      <Download size={14} />
                      PDF
                    </button>
                  </div>
                </>
              ) : (
                <p className="msg-error">{message.error ?? "Empty response"}</p>
              )}
              <HitlCards
                cards={message.hitlCards}
                userId={userId}
                orgId={orgId}
                onResolved={(card, resumed) => onHitlResolved(message.id, card, resumed)}
              />
            </div>
          ),
        )}

        {busy ? (
          <div className="msg assistant pending">
            <LoaderCircle className="spin" size={18} />
            <span>Agents working…</span>
          </div>
        ) : null}
        <div ref={bottomRef} />
      </main>

      <form
        className="composer"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <textarea
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Message Palatium…"
          rows={2}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
        />
        <button type="submit" disabled={!canSend} aria-label="Send">
          <SendHorizontal size={18} />
        </button>
      </form>
    </div>
  );
}
