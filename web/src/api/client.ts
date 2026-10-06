import type {
  ContentDocument,
  DialogTurnResponse,
  FormatterTaskResult,
  HITLCardView,
  HitlRespondResponse,
  HitlStepUpChallenge,
} from '../types/contentDocument';
import {
  getAuthToken,
  getRuntimeMode,
  requestHostTokenRefresh,
  setAuthToken,
} from '../runtime/auth';
import { t } from '../i18n';
import { adoptTraceIdFromResponse, getOrCreateTraceId, TRACE_HEADER } from '../lib/trace';
import { apiUrl } from '../runtime/endpoints';

/**
 * Клиентские лимиты, синхронизированные с Pydantic-схемой
 * `ClassifyIntentRequest` в `presentation/api/routers/intents.py`.
 * Если лимит в схеме изменится — обновить здесь.
 */
const MAX_INTENT_TEXT = 32_000;
const MAX_ATTACHMENTS = 5;

/** Public-export для использования в UI (счётчик символов, disabled-состояние). */
export const INTENT_TEXT_LIMIT = MAX_INTENT_TEXT;
export const INTENT_ATTACHMENT_LIMIT = MAX_ATTACHMENTS;

// ────────────────────────────────────────────────────────────────────────────
// Error humanization
// ────────────────────────────────────────────────────────────────────────────

type PydanticValidationError = {
  type?: string;
  loc?: (string | number)[];
  msg?: string;
  ctx?: { max_length?: number; min_length?: number };
};

/**
 * Новый (человекочитаемый) формат 422-ответа — см. `validation_error_handler`
 * в `presentation/app.py`. Поля: `field`, `code`, `message`.
 */
type ServerIssue = {
  field: string;
  code: string;
  message: string;
};

function isServerIssue(value: unknown): value is ServerIssue {
  if (typeof value !== 'object' || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.field === 'string' && typeof v.message === 'string';
}

/**
 * Преобразует одну ошибку Pydantic в короткое человекочитаемое сообщение.
 * FastAPI 422 возвращает массив таких объектов в `detail`.
 */
function humanizePydanticError(e: PydanticValidationError): string {
  const field = Array.isArray(e.loc) ? String(e.loc[e.loc.length - 1] ?? 'field') : 'field';

  switch (e.type) {
    case 'string_too_long': {
      const limit = e.ctx?.max_length ?? '?';
      return `«${field}»: максимум ${limit} символов`;
    }
    case 'string_too_short': {
      const min = e.ctx?.min_length ?? 1;
      return `«${field}»: минимум ${min} символ${min === 1 ? '' : 'а'}`;
    }
    case 'too_long': {
      const limit = e.ctx?.max_length ?? '?';
      return `«${field}»: максимум ${limit} элементов`;
    }
    case 'too_short': {
      const min = e.ctx?.min_length ?? 1;
      return `«${field}»: минимум ${min} элементов`;
    }
    case 'uuid_parsing':
      return `«${field}»: некорректный UUID`;
    case 'missing':
      return `«${field}»: обязательное поле`;
    case 'value_error':
      return `«${field}»: ${e.msg ?? 'некорректное значение'}`;
    default:
      return `«${field}»: ${e.msg ?? e.type ?? 'ошибка валидации'}`;
  }
}

/**
 * Human-readable failure text from an API response.
 *
 * Разбирает три случая:
 *  1. FastAPI HTTPException → `detail: "строка"` — возвращаем как есть.
 *  2. FastAPI RequestValidationError → `detail: [{...}]` — превращаем в «поле: сообщение; …».
 *  3. Всё остальное (не-JSON, пустое тело) — сырой текст, обрезанный до 300 символов.
 */
async function errorDetail(res: Response): Promise<string> {
  const raw = await res.text();

  try {
    const parsed = JSON.parse(raw) as { detail?: unknown };

    // Случай 1: HTTPException(detail="...")
    if (typeof parsed.detail === 'string' && parsed.detail.trim()) {
      return parsed.detail;
    }

    // Случай 2: RequestValidationError(detail=[{...}])
    if (Array.isArray(parsed.detail) && parsed.detail.length > 0) {
      const all = parsed.detail as unknown[];
      const head = all.slice(0, 3).map(item => {
        // Новый формат (validation_error_handler в app.py) — message готов.
        if (isServerIssue(item)) return item.message;
        // Legacy-формат (raw Pydantic dump) — humanize на клиенте.
        return humanizePydanticError(item as PydanticValidationError);
      });
      const suffix = all.length > 3 ? ` (+${all.length - 3} ещё)` : '';
      return head.join('; ') + suffix;
    }

    // Случай 3: detail — объект с message (кастомный handler)
    if (parsed.detail && typeof parsed.detail === 'object') {
      const obj = parsed.detail as { message?: string };
      if (typeof obj.message === 'string') return obj.message;
    }
  } catch {
    // Не JSON — не падаем, отдадим сырой текст
  }

  return raw.slice(0, 300) || `HTTP ${res.status}`;
}

/**
 * Ошибка API со СТАТУСОМ, а не только с текстом.
 *
 * Текст ответа человекочитаем, но по нему нельзя принять решение: сервер может
 * отдать `detail: "card expired"` без кода 410 внутри, и разбор статуса по
 * подстроке «410» ломается на первом же изменении текста на сервере. Поэтому
 * статус едет отдельным полем, а решение о поведении принимается по нему.
 */
export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** Единая точка превращения неуспешного ответа в ошибку со статусом. */
async function apiFailure(res: Response): Promise<ApiError> {
  return new ApiError(res.status, await errorDetail(res));
}

// ────────────────────────────────────────────────────────────────────────────
// Auth
// ────────────────────────────────────────────────────────────────────────────

/**
 * Mint dev-токена. Разрешён ТОЛЬКО в standalone-режиме.
 *
 * В embed это ошибка, а не «тихий fallback»: токен в СЭД выдаёт host, и
 * самостоятельный mint означал бы обход его модели доступа (020).
 */
async function mintDevToken(userId: string, orgId?: string | null): Promise<string> {
  if (getRuntimeMode() !== 'standalone') {
    throw new Error(t('error.devTokenDisabled'));
  }
  const res = await fetch(apiUrl('/auth/dev-token'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', [TRACE_HEADER]: getOrCreateTraceId() },
    body: JSON.stringify({ user_id: userId, ...(orgId ? { org_id: orgId } : {}) }),
  });
  adoptTraceIdFromResponse(res.headers.get(TRACE_HEADER));
  if (!res.ok) throw await apiFailure(res);
  const { access_token } = (await res.json()) as { access_token: string };
  setAuthToken(access_token);
  return access_token;
}

/**
 * Один «вылет» за токеном при параллельных запросах.
 *
 * Эффекты виджета (сокет сессии, гидратация истории) стартуют одновременно, а в dev
 * React вызывает их дважды, — без дедупликации это 5–6 одинаковых выпусков токена
 * на старте. Хост-режим дедуплицируется в `runtime/auth` (`pendingRefresh`); здесь
 * тот же приём, чтобы обе ветки велись одинаково.
 */
let pendingMint: Promise<string> | null = null;

function mintDevTokenOnce(userId: string, orgId?: string | null): Promise<string> {
  if (pendingMint) return pendingMint;
  const minted = mintDevToken(userId, orgId).finally(() => {
    pendingMint = null;
  });
  pendingMint = minted;
  return minted;
}

/**
 * Возвращает действующий access token.
 *
 * - standalone: dev-mint (или уже лежащий в памяти токен);
 * - host: только событие `sed:auth-token-requested` → `sed:auth-token-refreshed`.
 */
export async function ensureAccessToken(
  userId?: string | null,
  orgId?: string | null,
  forceRefresh = false
): Promise<string> {
  const existing = getAuthToken();
  if (existing && !forceRefresh) return existing;

  if (getRuntimeMode() === 'standalone') {
    if (!userId) {
      throw new Error(t('error.noToken'));
    }
    return mintDevTokenOnce(userId, orgId);
  }

  return requestHostTokenRefresh();
}

async function fetchWithAuth(
  input: string,
  init: RequestInit = {},
  userId?: string | null,
  orgId?: string | null,
  retries = 2,
  options: { rawBody?: boolean } = {}
): Promise<Response> {
  const token = await ensureAccessToken(userId, orgId);

  const headers = new Headers(init.headers);
  // A raw body (attachment bytes) keeps the media type set by the caller; forcing
  // application/json here would mislabel the payload and the store would reject it.
  if (!options.rawBody) headers.set('Content-Type', 'application/json');
  headers.set('Authorization', `Bearer ${token}`);
  headers.set(TRACE_HEADER, getOrCreateTraceId());

  /** Сеть и 5xx — единственное, что ретраится; ошибка refresh уходит наружу сразу. */
  const fetchWithRetry = async (url: string): Promise<Response> => {
    // Последняя 5xx сохраняется целиком: после исчерпания повторов пользователю
    // нужна ПРИЧИНА (текст ответа сервера), а не безадресное «запрос не выполнен».
    let lastFailure: ApiError | null = null;
    for (let attempt = 0; attempt <= retries; attempt++) {
      try {
        const res = await fetch(url, { ...init, headers });
        adoptTraceIdFromResponse(res.headers.get(TRACE_HEADER));
        headers.set(TRACE_HEADER, getOrCreateTraceId());
        if (res.ok || res.status < 500) return res;
        lastFailure = await apiFailure(res);
      } catch (err) {
        if (attempt === retries) {
          throw err instanceof Error ? err : new Error(t('error.requestFailed'));
        }
      }
      if (attempt < retries) await new Promise(r => setTimeout(r, 300 * (attempt + 1)));
    }
    throw lastFailure ?? new Error(t('error.requestFailed'));
  };

  // Адрес считает одна функция на весь виджет: абсолютный `input` (presigned-URL
  // объектного хранилища) возвращается как есть, остальное — от базы сборки.
  const url = apiUrl(input);
  const response = await fetchWithRetry(url);
  if (response.status !== 401) return response;

  // Ровно один повтор после обновления токена: refresh бросает сам, если host не
  // ответил, — глотать это в retry-цикле нельзя (иначе 3 × таймаут подряд).
  const refreshed = await ensureAccessToken(userId, orgId, true);
  headers.set('Authorization', `Bearer ${refreshed}`);
  return fetchWithRetry(url);
}

// ────────────────────────────────────────────────────────────────────────────
// Feedback
// ────────────────────────────────────────────────────────────────────────────

export async function sendFeedback(
  messageId: string,
  feedbackType: 'like' | 'dislike',
  userId?: string | null,
  orgId?: string | null
): Promise<void> {
  const res = await fetchWithAuth(
    '/feedback',
    {
      method: 'POST',
      body: JSON.stringify({
        message_id: messageId,
        feedback: feedbackType,
      }),
    },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
}

// ────────────────────────────────────────────────────────────────────────────
// Intent processing
// ────────────────────────────────────────────────────────────────────────────

export async function processIntent(
  text: string,
  threadId: string,
  userId?: string | null,
  orgId?: string | null,
  attachmentIds: readonly string[] = []
): Promise<FormatterTaskResult> {
  // Клиентская валидация — не даём запросу уйти, если он гарантированно 422.
  if (text.length === 0) {
    throw new Error(t('error.emptyMessage'));
  }
  if (text.length > MAX_INTENT_TEXT) {
    throw new Error(t('error.messageTooLong', { used: text.length, limit: MAX_INTENT_TEXT }));
  }
  if (attachmentIds.length > MAX_ATTACHMENTS) {
    throw new Error(t('error.tooManyAttachments', { count: MAX_ATTACHMENTS }));
  }

  const res = await fetchWithAuth(
    '/intents/process',
    {
      method: 'POST',
      body: JSON.stringify({
        text,
        thread_id: threadId,
        ...(attachmentIds.length > 0 ? { attachment_ids: attachmentIds } : {}),
      }),
    },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

// ────────────────────────────────────────────────────────────────────────────
// Attachments
// ────────────────────────────────────────────────────────────────────────────

/**
 * Attachment wire contracts (`presentation/api/routers/attachments.py`).
 * `upload_url` is a presigned PUT when the store has an HTTP surface of its own and
 * a `memory://…` placeholder when it does not — see `lib/attachments.ts` for the
 * strategy that picks the transport.
 */
export type AttachmentMode = 'attach' | 'index';

export type AttachmentStatus =
  | 'pending'
  | 'uploaded'
  | 'scanning'
  | 'ready'
  | 'quarantined'
  | 'rejected'
  | 'expired'
  | 'indexed';

export type AttachmentResponse = {
  attachment_id: string;
  thread_id: string | null;
  filename: string;
  mime_type: string;
  size_bytes: number;
  mode: AttachmentMode;
  status: AttachmentStatus;
  page_count: number | null;
  rejection_reason: string | null;
  error: string | null;
  created_at: string;
  expires_at: string | null;
};

export type AttachmentInitRequest = {
  thread_id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  mode?: AttachmentMode;
};

export type AttachmentInitResponse = {
  attachment_id: string;
  upload_url: string;
  expires_at: string;
  mode: AttachmentMode;
};

export async function initAttachmentUpload(
  body: AttachmentInitRequest,
  userId?: string | null,
  orgId?: string | null
): Promise<AttachmentInitResponse> {
  const res = await fetchWithAuth(
    '/attachments/init',
    { method: 'POST', body: JSON.stringify(body) },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

/**
 * PUT the bytes straight to the presigned URL.
 *
 * No bearer token and no trace header on purpose: this request is signed for the
 * object store, not for our API, and the signature does not cover Content-Type
 * (see `MinIOAdapter.presigned_put_url`), so the declared media type is sent as-is.
 *
 * The PUT is bounded by ``timeoutMs``: a public endpoint the browser cannot reach
 * (off-network object storage, a stale ``ATTACHMENTS_MINIO_PUBLIC_ENDPOINT``) would
 * otherwise leave the chip "uploading" until the OS TCP timeout. The caller treats
 * an abort like any other presign failure and re-sends through the API.
 */
export async function putAttachmentBytes(
  uploadUrl: string,
  body: Blob,
  contentType: string,
  timeoutMs = 15000
): Promise<void> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(uploadUrl, {
      method: 'PUT',
      body,
      headers: { 'Content-Type': contentType || 'application/octet-stream' },
      signal: controller.signal,
    });
    if (!res.ok) {
      throw new Error(`Storage upload ${res.status}: ${(await res.text()).slice(0, 200)}`);
    }
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Send the bytes through the API instead of the store.
 *
 * Used when the presigned URL is not reachable from the browser (the in-process dev
 * store) or when object storage stays off the client network. The server applies the
 * same size cap and pipeline, so this is a transport choice, not a relaxed path.
 */
export async function uploadAttachmentViaApi(
  attachmentId: string,
  body: Blob,
  contentType: string,
  userId?: string | null,
  orgId?: string | null
): Promise<AttachmentResponse> {
  const res = await fetchWithAuth(
    `/attachments/${encodeURIComponent(attachmentId)}/content`,
    { method: 'PUT', body, headers: { 'Content-Type': contentType } },
    userId,
    orgId,
    2,
    { rawBody: true }
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

export async function completeAttachmentUpload(
  attachmentId: string,
  userId?: string | null,
  orgId?: string | null
): Promise<AttachmentResponse> {
  const res = await fetchWithAuth(
    `/attachments/${encodeURIComponent(attachmentId)}/complete`,
    { method: 'POST' },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

export async function deleteAttachment(
  attachmentId: string,
  userId?: string | null,
  orgId?: string | null
): Promise<void> {
  const res = await fetchWithAuth(
    `/attachments/${encodeURIComponent(attachmentId)}`,
    { method: 'DELETE' },
    userId,
    orgId
  );
  if (!res.ok && res.status !== 404) throw await apiFailure(res);
}

// ────────────────────────────────────────────────────────────────────────────
// Sessions / dialogs
// ────────────────────────────────────────────────────────────────────────────

export async function fetchDialogTurns(
  threadId: string,
  limit = 50,
  userId?: string | null,
  orgId?: string | null
): Promise<DialogTurnResponse[]> {
  const res = await fetchWithAuth(
    `/sessions/${encodeURIComponent(threadId)}/turns?limit=${limit}`,
    { method: 'GET' },
    userId,
    orgId
  );
  if (res.status === 404) return [];
  if (!res.ok) throw await apiFailure(res);
  const json = (await res.json()) as { items: DialogTurnResponse[] };
  return json.items ?? [];
}

// ────────────────────────────────────────────────────────────────────────────
// HITL
// ────────────────────────────────────────────────────────────────────────────

export async function fetchHitlCard(
  cardId: string,
  userId?: string | null,
  orgId?: string | null
): Promise<HITLCardView> {
  const res = await fetchWithAuth(
    `/hitl/${encodeURIComponent(cardId)}`,
    { method: 'GET' },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

export async function fetchHitlStepUpChallenge(
  cardId: string,
  userId?: string | null,
  orgId?: string | null
): Promise<HitlStepUpChallenge> {
  const res = await fetchWithAuth(
    `/hitl/${encodeURIComponent(cardId)}/step-up-challenge`,
    { method: 'POST', body: '{}' },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

export async function respondHitlCard(
  cardId: string,
  actionId: string,
  actionToken: string,
  idempotencyKey: string,
  userId?: string | null,
  orgId?: string | null,
  stepUpAssertion?: string | null
): Promise<HitlRespondResponse> {
  const res = await fetchWithAuth(
    `/hitl/${encodeURIComponent(cardId)}/respond`,
    {
      method: 'POST',
      body: JSON.stringify({
        action_id: actionId,
        action_token: actionToken,
        idempotency_key: idempotencyKey,
        ...(stepUpAssertion ? { step_up_assertion: stepUpAssertion } : {}),
      }),
    },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

// ────────────────────────────────────────────────────────────────────────────
// Memory
// ────────────────────────────────────────────────────────────────────────────

export type MemorySaveRequest = {
  thread_id: string;
  text: string;
  entry_key: string;
  namespace_kind?: 'thread' | 'user' | 'org';
  scope_id?: string;
  memory_type?: 'preference' | 'fact' | 'incident' | 'episode';
  contains_pii?: boolean;
};

export type MemoryForgetRequest = {
  thread_id: string;
  entry_key: string;
  namespace_kind?: 'thread' | 'user' | 'org';
  scope_id?: string;
};

export type MemoryConsolidateRequest = {
  thread_id: string;
  consolidate_task_id?: string;
};

export async function requestMemorySave(
  body: MemorySaveRequest,
  userId?: string | null,
  orgId?: string | null
): Promise<HITLCardView> {
  const res = await fetchWithAuth(
    '/memory/save',
    { method: 'POST', body: JSON.stringify(body) },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

export async function requestMemoryForget(
  body: MemoryForgetRequest,
  userId?: string | null,
  orgId?: string | null
): Promise<HITLCardView> {
  const res = await fetchWithAuth(
    '/memory/forget',
    { method: 'POST', body: JSON.stringify(body) },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

export async function requestMemoryConsolidate(
  body: MemoryConsolidateRequest,
  userId?: string | null,
  orgId?: string | null
): Promise<HITLCardView> {
  const res = await fetchWithAuth(
    '/memory/consolidate',
    { method: 'POST', body: JSON.stringify(body) },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  return res.json();
}

// ────────────────────────────────────────────────────────────────────────────
// Documents
// ────────────────────────────────────────────────────────────────────────────

export async function downloadDocumentPdf(
  doc: ContentDocument,
  threadId: string,
  userId?: string | null,
  orgId?: string | null
): Promise<void> {
  const res = await fetchWithAuth(
    '/documents/export/pdf',
    {
      method: 'POST',
      body: JSON.stringify({ thread_id: threadId, document: doc }),
    },
    userId,
    orgId
  );
  if (!res.ok) throw await apiFailure(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  const match = res.headers.get('Content-Disposition')?.match(/filename="(.+?)"/);
  a.href = url;
  a.download = match?.[1] ?? 'palatium-answer.pdf';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
