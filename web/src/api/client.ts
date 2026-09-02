import type {
  ContentDocument,
  FormatterTaskResult,
  HITLCardView,
  HitlRespondResponse,
} from '../types/contentDocument';

const TOKEN_STORAGE_KEY = 'palatium.access_token';
const BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';

function writeStoredToken(token: string): void {
  try {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
    localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {}
}

function readStoredToken(): string | null {
  try {
    return sessionStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

async function mintDevToken(userId: string, orgId?: string | null): Promise<string> {
  const res = await fetch(`${BASE_URL}/auth/dev-token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, ...(orgId ? { org_id: orgId } : {}) }),
  });
  if (!res.ok) throw new Error(`Auth ${res.status}: ${await res.text()}`);
  const { access_token } = await res.json();
  writeStoredToken(access_token);
  return access_token;
}

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
        ...(orgId ? { org_id: orgId } : {}),
      }),
    },
    userId,
    orgId
  );
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Feedback ${res.status}: ${detail.slice(0, 300)}`);
  }
}

export async function ensureAccessToken(
  userId: string,
  orgId?: string | null,
  forceRefresh = false
): Promise<string> {
  if (!forceRefresh) {
    const existing = readStoredToken();
    if (existing) return existing;
  }
  return mintDevToken(userId, orgId);
}

async function fetchWithAuth(
  input: string,
  init: RequestInit = {},
  userId?: string | null,
  orgId?: string | null,
  retries = 2
): Promise<Response> {
  let token = userId ? await ensureAccessToken(userId, orgId) : readStoredToken();
  if (!token) throw new Error('No access token available');

  const headers = new Headers(init.headers);
  headers.set('Content-Type', 'application/json');
  headers.set('Authorization', `Bearer ${token}`);

  const doFetch = async (): Promise<Response> => {
    const url = input.startsWith('http') ? input : `${BASE_URL}${input}`;
    const response = await fetch(url, { ...init, headers });
    if (response.status === 401 && userId) {
      token = await ensureAccessToken(userId, orgId, true);
      headers.set('Authorization', `Bearer ${token}`);
      return fetch(url, { ...init, headers });
    }
    return response;
  };

  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const res = await doFetch();
      if (res.ok || res.status < 500) return res;
    } catch {
      if (attempt === retries) throw new Error(`Request failed after ${retries} retries`);
      await new Promise(r => setTimeout(r, 300 * (attempt + 1)));
    }
  }
  throw new Error(`Request failed after ${retries} retries`);
}

export async function processIntent(
  text: string,
  threadId: string,
  userId?: string | null,
  orgId?: string | null
): Promise<FormatterTaskResult> {
  const res = await fetchWithAuth(
    '/intents/process',
    {
      method: 'POST',
      body: JSON.stringify({ text, thread_id: threadId, ...(orgId ? { org_id: orgId } : {}) }),
    },
    userId,
    orgId
  );
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchDialogTurns(
  threadId: string,
  limit = 50,
  userId?: string | null,
  orgId?: string | null
): Promise<any[]> {
  const res = await fetchWithAuth(
    `/sessions/${encodeURIComponent(threadId)}/turns?limit=${limit}`,
    { method: 'GET' },
    userId,
    orgId
  );
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(await res.text());
  const json = (await res.json()) as { items: any[] };
  return json.items ?? [];
}

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
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function fetchHitlStepUpChallenge(
  cardId: string,
  userId?: string | null,
  orgId?: string | null
): Promise<any> {
  const res = await fetchWithAuth(
    `/hitl/${encodeURIComponent(cardId)}/step-up-challenge`,
    { method: 'POST', body: '{}' },
    userId,
    orgId
  );
  if (!res.ok) throw new Error(await res.text());
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
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

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
  if (!res.ok) throw new Error(await res.text());
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
