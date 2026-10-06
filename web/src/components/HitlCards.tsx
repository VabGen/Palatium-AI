import { useEffect, useState } from 'react';
import { ListChecks, ShieldAlert } from 'lucide-react';
import { fetchHitlStepUpChallenge, respondHitlCard } from '../api/client';
import { formatHitlError } from '../lib/hitl';
import { formatDateTime, formatNumber, t } from '../i18n';
import { TokenIcon } from '../icons/TokenIcon';
import type {
  FormatterTaskResult,
  HITLCardView,
  HitlStepUpChallenge,
} from '../types/contentDocument';

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

const STEP_UP_MESSAGE_TYPE = 'palatium.hitl.step_up';

/** Claim name the server binds the assertion to when it does not name one itself. */
const DEFAULT_STEP_UP_CLAIM = 'hitl_card_id';

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
    target.searchParams.set('return_origin', window.location.origin);
    window.open(target.toString(), 'palatium-hitl-step-up', 'noopener,noreferrer');
  } catch {
    window.open(url, 'palatium-hitl-step-up', 'noopener,noreferrer');
  }
}

export function HitlCards({ cards, userId, orgId, onResolved }: HitlCardsProps) {
  const pendingCards = cards.filter(card => card.status === 'pending');
  if (pendingCards.length === 0) return null;
  return (
    <div className="hitl-stack">
      {pendingCards.map(card => (
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
  const [stepUpAssertion, setStepUpAssertion] = useState('');

  const pending = local.status === 'pending';
  const isChoice = local.purpose === 'user_choice';
  const isTool = local.purpose === 'mcp_tool_approval';
  const isReview = local.purpose === 'quality_review';
  const Mark = isChoice ? ListChecks : ShieldAlert;
  const mayNeedStepUp = isTool;

  useEffect(() => {
    if (!stepUpPending?.challenge.authorize_url) return;
    const expectedOrigin = authorizeOrigin(stepUpPending.challenge.authorize_url);
    if (!expectedOrigin) return;

    function onMessage(event: MessageEvent) {
      if (event.origin !== expectedOrigin) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      const payload = data as { type?: unknown; assertion?: unknown };
      if (payload.type !== STEP_UP_MESSAGE_TYPE) return;
      if (typeof payload.assertion !== 'string' || !payload.assertion.trim()) return;
      setStepUpAssertion(payload.assertion.trim());
    }

    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
  }, [stepUpPending]);

  async function completeRespond(actionId: string, actionToken: string, assertion: string | null) {
    const idempotencyKey = `ui-${local.card_id}-${actionId}`;
    const result = await respondHitlCard(
      local.card_id,
      actionId,
      actionToken,
      idempotencyKey,
      userId,
      orgId,
      assertion
    );
    setLocal(result.resolve.card);
    setStepUpPending(null);
    setStepUpAssertion('');
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
          } else if (challenge.method === 'idp_acr' || challenge.method === 'webauthn') {
            setStepUpPending({ actionId, actionToken, challenge });
            if (challenge.authorize_url) {
              openAuthorizeUrl(challenge.authorize_url);
            }
            return;
          } else {
            throw new Error(t('hitl.error.stepUpUnavailable'));
          }
        }
      }
      await completeRespond(actionId, actionToken, assertion);
    } catch (err) {
      setError(formatHitlError(err));
    } finally {
      setBusyAction(null);
    }
  }

  async function submitIdpAssertion() {
    if (!stepUpPending || busyAction) return;
    const token = stepUpAssertion.trim();
    if (!token) {
      setError(t('hitl.error.stepUpRequired'));
      return;
    }
    setBusyAction(stepUpPending.actionId);
    setError(null);
    try {
      await completeRespond(stepUpPending.actionId, stepUpPending.actionToken, token);
    } catch (err) {
      setError(formatHitlError(err));
    } finally {
      setBusyAction(null);
    }
  }

  const purposeClass = isChoice
    ? 'hitl-choice'
    : isTool
      ? 'hitl-tool'
      : isReview
        ? 'hitl-review'
        : '';
  const riskColor =
    local.risk_score >= 0.7
      ? 'var(--danger)'
      : local.risk_score >= 0.4
        ? 'var(--warning)'
        : 'var(--success)';

  return (
    <section
      className={`hitl-card status-${local.status}${purposeClass ? ` ${purposeClass}` : ''}`}
      aria-live="polite"
    >
      <header className="hitl-header">
        <Mark size={18} className="hitl-mark icon-animated" />
        <div>
          <p className="hitl-kicker">
            {isChoice
              ? t('hitl.kicker.choice')
              : isTool
                ? t('hitl.kicker.tool')
                : t('hitl.kicker.review')}
          </p>
          <h3>{local.title}</h3>
          {local.body && <p>{local.body}</p>}
          {isChoice && pending && <p className="hitl-choice-hint">{t('hitl.choiceHint')}</p>}
          {mayNeedStepUp && <p className="hitl-step-up-hint">{t('hitl.stepUpHint')}</p>}
        </div>
      </header>

      <div className="hitl-meta">
        {!isChoice && (
          <span>
            {t('hitl.riskLabel')}{' '}
            <span style={{ color: riskColor }}>
              {formatNumber(local.risk_score, {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
              })}
            </span>
          </span>
        )}
        <span>{t('hitl.expires', { time: formatDateTime(local.expires_at) })}</span>
        <span className="hitl-status">{local.status}</span>
      </div>

      {stepUpPending ? (
        <div className="hitl-step-up-form" role="group" aria-label={t('hitl.stepUpGroup')}>
          <p className="hitl-step-up-hint">
            {t('hitl.stepUpVia', {
              method: stepUpPending.challenge.method,
              acr: stepUpPending.challenge.required_acr
                ? ` (acr=${stepUpPending.challenge.required_acr})`
                : '',
            })}{' '}
            {t('hitl.stepUpBind', {
              claim: stepUpPending.challenge.card_claim ?? DEFAULT_STEP_UP_CLAIM,
              card: local.card_id,
            })}
            {stepUpPending.challenge.challenge
              ? t('hitl.stepUpNonce', { nonce: stepUpPending.challenge.challenge })
              : ''}
            {stepUpPending.challenge.authorize_url
              ? t('hitl.stepUpIdpOpened')
              : t('hitl.stepUpPaste')}
          </p>
          <textarea
            className="hitl-step-up-input"
            rows={3}
            value={stepUpAssertion}
            onChange={event => setStepUpAssertion(event.target.value)}
            placeholder={t('hitl.stepUpPlaceholder')}
            disabled={busyAction !== null}
          />
          <div className="hitl-options">
            {stepUpPending.challenge.authorize_url && (
              <button
                type="button"
                className="action-card action-secondary"
                disabled={busyAction !== null}
                onClick={() => {
                  const url = stepUpPending.challenge.authorize_url;
                  if (url) openAuthorizeUrl(url);
                }}
              >
                <span>{t('hitl.stepUpOpenIdp')}</span>
              </button>
            )}
            <button
              type="button"
              className="action-card action-primary"
              disabled={busyAction !== null}
              onClick={() => void submitIdpAssertion()}
            >
              <span>{busyAction ? t('hitl.stepUpConfirming') : t('hitl.stepUpSubmit')}</span>
            </button>
            <button
              type="button"
              className="action-card action-secondary"
              disabled={busyAction !== null}
              onClick={() => {
                setStepUpPending(null);
                setStepUpAssertion('');
              }}
            >
              <span>{t('hitl.cancel')}</span>
            </button>
          </div>
        </div>
      ) : pending ? (
        <div
          className={`hitl-options${isChoice ? ' hitl-options-choice' : ''}`}
          role="group"
          aria-label={isChoice ? t('hitl.choicesLabel') : t('hitl.actionsLabel')}
        >
          {local.options.map(option => (
            <button
              key={option.action_id}
              type="button"
              className={`action-card action-${option.style}${isChoice ? ' action-choice' : ''}`}
              disabled={busyAction !== null}
              onClick={() => void choose(option.action_id, option.action_token)}
            >
              <TokenIcon token={option.icon} size={16} animated={option.style === 'primary'} />
              <span>
                {busyAction === option.action_id
                  ? mayNeedStepUp
                    ? t('hitl.stepUpConfirming')
                    : t('hitl.saving')
                  : option.label}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="hitl-resolved">
          {t('hitl.resolved', { action: local.resolved_action_id ?? local.status })}
        </p>
      )}
      {error && <p className="msg-error">{error}</p>}
    </section>
  );
}
