import { useEffect, useState } from "react";
import { ListChecks, ShieldAlert } from "lucide-react";
import {
  fetchHitlStepUpChallenge,
  respondHitlCard,
  type HitlStepUpChallenge,
} from "../api/client";
import { TokenIcon } from "../icons/TokenIcon";
import type { FormatterTaskResult, HITLCardView } from "../types/contentDocument";

type HitlCardsProps = {
  cards: HITLCardView[];
  userId?: string | null;
  orgId?: string | null;
  onResolved: (card: HITLCardView, resumed?: FormatterTaskResult | null) => void;
};

type PendingStepUp = {
  actionId: string;
  actionToken: string;
  challenge: HitlStepUpChallenge;
};

const STEP_UP_MESSAGE_TYPE = "palatium.hitl.step_up";

function authorizeOrigin(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    return new URL(url).origin;
  } catch {
    return null;
  }
}

function openAuthorizeUrl(url: string): void {
  try {
    const target = new URL(url);
    target.searchParams.set("return_origin", window.location.origin);
    window.open(target.toString(), "palatium-hitl-step-up", "noopener,noreferrer");
  } catch {
    window.open(url, "palatium-hitl-step-up", "noopener,noreferrer");
  }
}

export function HitlCards({ cards, userId, orgId, onResolved }: HitlCardsProps) {
  if (cards.length === 0) return null;
  const pendingCards = cards.filter((card) => card.status === "pending");
  if (pendingCards.length === 0) return null;
  return (
    <div className="hitl-stack">
      {pendingCards.map((card) => (
        <HitlCard
          key={card.card_id}
          card={card}
          userId={userId}
          orgId={orgId}
          onResolved={onResolved}
        />
      ))}
    </div>
  );
}

function HitlCard({
  card,
  userId,
  orgId,
  onResolved,
}: {
  card: HITLCardView;
  userId?: string | null;
  orgId?: string | null;
  onResolved: (card: HITLCardView, resumed?: FormatterTaskResult | null) => void;
}) {
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [local, setLocal] = useState(card);
  const [stepUpPending, setStepUpPending] = useState<PendingStepUp | null>(null);
  const [stepUpAssertion, setStepUpAssertion] = useState("");
  const pending = local.status === "pending";
  const isChoice = local.purpose === "user_choice";
  const Mark = isChoice ? ListChecks : ShieldAlert;
  const mayNeedStepUp = local.purpose === "mcp_tool_approval";

  useEffect(() => {
    if (!stepUpPending?.challenge.authorize_url) return;
    const expectedOrigin = authorizeOrigin(stepUpPending.challenge.authorize_url);
    if (!expectedOrigin) return;

    function onMessage(event: MessageEvent) {
      if (event.origin !== expectedOrigin) return;
      const data = event.data;
      if (!data || typeof data !== "object") return;
      const payload = data as { type?: unknown; assertion?: unknown };
      if (payload.type !== STEP_UP_MESSAGE_TYPE) return;
      if (typeof payload.assertion !== "string" || !payload.assertion.trim()) return;
      setStepUpAssertion(payload.assertion.trim());
    }

    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [stepUpPending]);

  async function completeRespond(
    actionId: string,
    actionToken: string,
    assertion: string | null,
  ) {
    const idempotencyKey = `ui-${local.card_id}-${actionId}`;
    const result = await respondHitlCard(
      local.card_id,
      actionId,
      actionToken,
      idempotencyKey,
      userId,
      orgId,
      assertion,
    );
    setLocal(result.resolve.card);
    setStepUpPending(null);
    setStepUpAssertion("");
    onResolved(result.resolve.card, result.resumed);
  }

  async function choose(actionId: string, actionToken: string) {
    if (!pending || busyAction || stepUpPending) return;
    setBusyAction(actionId);
    setError(null);
    try {
      let assertion: string | null = null;
      if (mayNeedStepUp) {
        const challenge = await fetchHitlStepUpChallenge(local.card_id, userId, orgId);
        if (challenge.required) {
          if (challenge.assertion) {
            assertion = challenge.assertion;
            if (challenge.method === "idp_acr" || challenge.method === "webauthn") {
            setStepUpPending({ actionId, actionToken, challenge });
            if (challenge.authorize_url) {
              openAuthorizeUrl(challenge.authorize_url);
            }
            return;
          } else {
            throw new Error("Step-up required but no assertion returned");
          }
        }
      }
      await completeRespond(actionId, actionToken, assertion);
    } catch (err) {
      setError(err instanceof Error ? err.message : "HITL failed");
    } finally {
      setBusyAction(null);
    }
  }

  async function submitIdpAssertion() {
    if (!stepUpPending || busyAction) return;
    const token = stepUpAssertion.trim();
    if (!token) {
      setError("Provide the IdP step-up JWT (paste or IdP postMessage) before confirming.");
      return;
    }
    setBusyAction(stepUpPending.actionId);
    setError(null);
    try {
      await completeRespond(stepUpPending.actionId, stepUpPending.actionToken, token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "HITL failed");
    } finally {
      setBusyAction(null);
    }
  }

  return (
    <section
      className={`hitl-card status-${local.status}${isChoice ? " hitl-choice" : ""}`}
      aria-live="polite"
    >
      <header className="hitl-header">
        <Mark size={18} className="hitl-mark icon-animated" />
        <div>
          <h3>{local.title}</h3>
          {local.body ? <p>{local.body}</p> : null}
          {mayNeedStepUp ? (
            <p className="hitl-step-up-hint">
              Tool approval may require a server-issued step-up proof before the action runs.
            </p>
          ) : null}
        </div>
      </header>
      <div className="hitl-meta">
        {!isChoice ? <span>Risk {local.risk_score.toFixed(2)}</span> : null}
        <span>Expires {new Date(local.expires_at).toLocaleTimeString()}</span>
        <span className="hitl-status">{local.status}</span>
      </div>
      {stepUpPending ? (
        <div className="hitl-step-up-form" role="group" aria-label="IdP step-up assertion">
          <p className="hitl-step-up-hint">
            Step-up via {stepUpPending.challenge.method}
            {stepUpPending.challenge.required_acr
              ? ` (acr=${stepUpPending.challenge.required_acr})`
              : ""}
            . Bind claim{" "}
            <code>{stepUpPending.challenge.card_claim ?? "hitl_card_id"}</code>=
            <code>{local.card_id}</code>
            {stepUpPending.challenge.challenge
              ? `; challenge nonce ${stepUpPending.challenge.challenge}`
              : ""}
            .
            {stepUpPending.challenge.authorize_url
              ? " IdP window opened when available; it may postMessage the JWT."
              : " Paste the IdP JWT below."}
          </p>
          <textarea
            className="hitl-step-up-input"
            rows={3}
            value={stepUpAssertion}
            onChange={(event) => setStepUpAssertion(event.target.value)}
            placeholder="IdP step-up JWT"
            disabled={busyAction !== null}
          />
          <div className="hitl-options">
            {stepUpPending.challenge.authorize_url ? (
              <button
                type="button"
                className="action-card action-secondary"
                disabled={busyAction !== null}
                onClick={() => {
                  const url = stepUpPending.challenge.authorize_url;
                  if (url) openAuthorizeUrl(url);
                }}
              >
                <span>Open IdP</span>
              </button>
            ) : null}
            <button
              type="button"
              className="action-card action-primary"
              disabled={busyAction !== null}
              onClick={() => void submitIdpAssertion()}
            >
              <span>{busyAction ? "Confirming…" : "Submit step-up"}</span>
            </button>
            <button
              type="button"
              className="action-card action-secondary"
              disabled={busyAction !== null}
              onClick={() => {
                setStepUpPending(null);
                setStepUpAssertion("");
              }}
            >
              <span>Cancel</span>
            </button>
          </div>
        </div>
      ) : pending ? (
        <div
          className="hitl-options"
          role="group"
          aria-label={isChoice ? "Choices" : "HITL actions"}
        >
          {local.options.map((option) => (
            <button
              key={option.action_id}
              type="button"
              className={`action-card action-${option.style}`}
              disabled={busyAction !== null}
              onClick={() => void choose(option.action_id, option.action_token)}
            >
              <TokenIcon token={option.icon} size={16} animated={option.style === "primary"} />
              <span>
                {busyAction === option.action_id
                  ? mayNeedStepUp
                    ? "Confirming…"
                    : "Saving…"
                  : option.label}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="hitl-resolved">
          Resolved: {local.resolved_action_id ?? local.status}
        </p>
      )}
      {error ? <p className="msg-error">{error}</p> : null}
    </section>
  );
}
