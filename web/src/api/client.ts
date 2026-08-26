const TOKEN_STORAGE_KEY = "palatium.access_token";

import type {
  ContentDocument,
  FormatterTaskResult,
  HitlRespondResponse,
  HITLCardView,
  HITLResolveResult,
} from "../types/contentDocument";

type AuthHeaders = Record<string, string>;

function writeStoredToken(token: string): void {
  try {
    window.sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  } catch {
    /* ignore quota / private mode */
  }
  try {
    // Migrate off durable localStorage (XSS / shared-machine persistence risk).
    window.localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {
    /* ignore */
  }
}

function readStoredToken(): string | null {
  try {
    const fromSession = window.sessionStorage.getItem(TOKEN_STORAGE_KEY);
    if (fromSession) {
      return fromSession;
    }
  } catch {
    /* ignore */
  }
  try {
    const legacy = window.localStorage.getItem(TOKEN_STORAGE_KEY);
    if (legacy) {
      writeStoredToken(legacy);
      return legacy;
    }
  } catch {
    /* ignore */
  }
  return null;
}

async function mintDevToken(userId: string, orgId?: string | null): Promise<string> {
  const response = await fetch("/api/auth/dev-token", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user_id: userId,
      ...(orgId ? { org_id: orgId } : {}),
    }),
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Auth ${response.status}: ${detail.slice(0, 300)}`);
  }
  const body = (await response.json()) as { access_token: string };
  writeStoredToken(body.access_token);
  return body.access_token;
}

export async function ensureAccessToken(
  userId: string,
  orgId?: string | null,
  forceRefresh = false,
): Promise<string> {
  if (!forceRefresh) {
    const existing = readStoredToken();
    if (existing) {
      return existing;
    }
  }
  return mintDevToken(userId, orgId);
}

async function authHeaders(
  userId?: string | null,
  orgId?: string | null,
  forceRefresh = false,
): Promise<AuthHeaders> {
  if (!userId) {
    const existing = readStoredToken();
    if (!existing) {
      throw new Error("Missing user id for API auth");
    }
    return {
      "Content-Type": "application/json",
      Authorization: `Bearer ${existing}`,
    };
  }
  const token = await ensureAccessToken(userId, orgId, forceRefresh);
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
  };
}

async function fetchWithAuth(
  input: string,
  init: RequestInit,
  userId?: string | null,
  orgId?: string | null,
): Promise<Response> {
  const headers = await authHeaders(userId, orgId);
  let response = await fetch(input, {
    ...init,
    headers: { ...headers, ...(init.headers as AuthHeaders | undefined) },
  });
  if (response.status === 401 && userId) {
    const refreshed = await authHeaders(userId, orgId, true);
    response = await fetch(input, {
      ...init,
      headers: { ...refreshed, ...(init.headers as AuthHeaders | undefined) },
    });
  }
  return response;
}

export async function processIntent(
  text: string,
  threadId: string,
  userId?: string | null,
  orgId?: string | null,
): Promise<FormatterTaskResult> {
  const response = await fetchWithAuth(
    "/api/intents/process",
    {
      method: "POST",
      body: JSON.stringify({
        text,
        thread_id: threadId,
        ...(orgId ? { org_id: orgId } : {}),
      }),
    },
    userId,
    orgId,
  );

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`API ${response.status}: ${detail.slice(0, 300)}`);
  }

  return (await response.json()) as FormatterTaskResult;
}

export type DialogTurnDto = {
  id: string | null;
  thread_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  payload?: ContentDocument | Record<string, unknown> | null;
  task_id: string | null;
  seq: number;
  created_at: string | null;
};

export async function fetchDialogTurns(
  threadId: string,
  limit = 50,
  userId?: string | null,
  orgId?: string | null,
): Promise<DialogTurnDto[]> {
  const response = await fetchWithAuth(
    `/api/sessions/${encodeURIComponent(threadId)}/turns?limit=${limit}`,
    { method: "GET" },
    userId,
    orgId,
  );
  if (response.status === 404) {
    return [];
  }
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Turns ${response.status}: ${detail.slice(0, 300)}`);
  }
  const body = (await response.json()) as { items: DialogTurnDto[] };
  return body.items ?? [];
}

export async function fetchHitlCard(
  cardId: string,
  userId?: string | null,
  orgId?: string | null,
): Promise<HITLCardView> {
  const response = await fetchWithAuth(
    `/api/hitl/${encodeURIComponent(cardId)}`,
    { method: "GET" },
    userId,
    orgId,
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`HITL get ${response.status}: ${detail.slice(0, 300)}`);
  }
  return (await response.json()) as HITLCardView;
}

export type HitlStepUpChallenge = {
  required: boolean;
  method: "none" | "hmac_stub" | "idp_acr" | "webauthn";
  assertion?: string | null;
  challenge?: string | null;
  required_acr?: string | null;
  required_amr?: string[];
  card_claim?: string | null;
  authorize_url?: string | null;
  card_id: string;
};

export async function fetchHitlStepUpChallenge(
  cardId: string,
  userId?: string | null,
  orgId?: string | null,
): Promise<HitlStepUpChallenge> {
  const response = await fetchWithAuth(
    `/api/hitl/${encodeURIComponent(cardId)}/step-up-challenge`,
    { method: "POST", body: "{}" },
    userId,
    orgId,
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`HITL step-up ${response.status}: ${detail.slice(0, 300)}`);
  }
  return (await response.json()) as HitlStepUpChallenge;
}

export async function respondHitlCard(
  cardId: string,
  actionId: string,
  actionToken: string,
  idempotencyKey: string,
  userId?: string | null,
  orgId?: string | null,
  stepUpAssertion?: string | null,
): Promise<HitlRespondResponse> {
  const response = await fetchWithAuth(
    `/api/hitl/${cardId}/respond`,
    {
      method: "POST",
      body: JSON.stringify({
        action_id: actionId,
        action_token: actionToken,
        idempotency_key: idempotencyKey,
        ...(stepUpAssertion ? { step_up_assertion: stepUpAssertion } : {}),
      }),
    },
    userId,
    orgId,
  );

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`HITL ${response.status}: ${detail.slice(0, 300)}`);
  }

  const body = (await response.json()) as HitlRespondResponse | HITLResolveResult;
  if ("resolve" in body && body.resolve) {
    return body;
  }
  // Backward-compatible unwrap if server ever returns bare resolve.
  return { resolve: body as HITLResolveResult, resumed: null };
}

export async function downloadDocumentPdf(
  doc: ContentDocument,
  threadId: string,
  userId?: string | null,
  orgId?: string | null,
): Promise<void> {
  const response = await fetchWithAuth(
    "/api/documents/export/pdf",
    {
      method: "POST",
      body: JSON.stringify({
        thread_id: threadId,
        document: doc,
      }),
    },
    userId,
    orgId,
  );
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`PDF ${response.status}: ${detail.slice(0, 300)}`);
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement("a");
  const disposition = response.headers.get("Content-Disposition");
  const match = disposition?.match(/filename="(.+?)"/);
  anchor.href = url;
  anchor.download = match?.[1] ?? "palatium-answer.pdf";
  anchor.click();
  URL.revokeObjectURL(url);
}
