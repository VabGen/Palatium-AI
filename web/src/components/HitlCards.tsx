import { useEffect, useState, type ReactNode } from 'react';
import { fetchHitlStepUpChallenge, respondHitlCard } from '../api/client';
import { formatHitlError } from '../lib/hitl';
import { formatDateTime, t } from '../i18n';
import { AttachmentFileIcon, attachmentFileKind } from '../icons/fileTypeIcons';
import {
  GlyphExclamation,
  GlyphSafe,
  GlyphTodo,
} from '../icons/kimiTokenGlyphs';
import { TokenIcon } from '../icons/TokenIcon';
import { iconForActionKind } from '../icons/semanticIcons';
import type {
  DocumentRevision,
  FormatterTaskResult,
  HITLCardPurpose,
  HITLCardView,
  HitlStepUpChallenge,
} from '../types/contentDocument';
import type { MessageKey } from '../i18n/messages';

const HITL_STATUS_KEYS = {
  pending: 'hitl.status.pending',
  resolved: 'hitl.status.resolved',
  expired: 'hitl.status.expired',
  escalated: 'hitl.status.escalated',
  auto_rejected: 'hitl.status.auto_rejected',
  dead_letter: 'hitl.status.dead_letter',
} as const satisfies Record<HITLCardView['status'], MessageKey>;

const HITL_BUSY_KEYS = {
  user_choice: 'hitl.busy.choice',
  quality_review: 'hitl.busy.review',
  mcp_tool_approval: 'hitl.busy.tool',
} as const satisfies Record<HITLCardPurpose, MessageKey>;

function hitlStatusLabel(status: HITLCardView['status']): string {
  return t(HITL_STATUS_KEYS[status]);
}

/** Busy copy must match purpose: choice/reread is not a write (055 — no one-size «Saving»). */
function hitlBusyLabel(
  purpose: HITLCardPurpose | undefined,
  stepUpInFlight: boolean
): string {
  if (stepUpInFlight) return t('hitl.stepUpConfirming');
  if (purpose && purpose in HITL_BUSY_KEYS) {
    return t(HITL_BUSY_KEYS[purpose]);
  }
  return t('hitl.busy.review');
}

/** Result of resolving one card: who was resolved, and the turn it produced (if any). */
export type HitlResolvedEvent = {
  card: HITLCardView;
  resumed?: FormatterTaskResult | null;
  revision?: DocumentRevision | null;
};

type HitlCardsProps = {
  cards: HITLCardView[];
  userId?: string | null;
  orgId?: string | null;
  onResolved: (event: HitlResolvedEvent) => void;
};

type PendingStepUp = {
  actionId: string;
  actionToken: string;
  challenge: HitlStepUpChallenge;
};

const STEP_UP_MESSAGE_TYPE = 'palatium.hitl.step_up';

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
  onResolved: (event: HitlResolvedEvent) => void;
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
  // Official Kimi filled glyphs (widget icon system) — not Lucide stroke chrome.
  const Mark = isChoice ? GlyphTodo : isTool ? GlyphSafe : GlyphExclamation;
  const mayNeedStepUp = isTool;

  function optionLeading(option: HITLCardView['options'][number]): ReactNode {
    const explicit = option.icon ?? iconForActionKind(option.kind);
    if (explicit) {
      return <TokenIcon token={explicit} size={16} />;
    }
    if (isChoice && /\.\w{2,5}$/i.test(option.label.trim())) {
      return (
        <AttachmentFileIcon kind={attachmentFileKind(option.label.trim())} size={20} />
      );
    }
    return null;
  }

  useEffect(() => {
    if (!stepUpPending?.challenge.authorize_url) return;
    const expectedOrigin = authorizeOrigin(stepUpPending.challenge.authorize_url);
    if (!expectedOrigin) return;
    const pending = stepUpPending;

    function onMessage(event: MessageEvent) {
      if (event.origin !== expectedOrigin) return;
      const data = event.data;
      if (!data || typeof data !== 'object') return;
      const payload = data as { type?: unknown; assertion?: unknown };
      if (payload.type !== STEP_UP_MESSAGE_TYPE) return;
      if (typeof payload.assertion !== 'string' || !payload.assertion.trim()) return;
      const assertion = payload.assertion.trim();
      setStepUpAssertion(assertion);
      // Big Tech: IdP return completes the card — no paste/JWT chrome for the user.
      setBusyAction(pending.actionId);
      setError(null);
      void completeRespond(pending.actionId, pending.actionToken, assertion)
        .catch(err => setError(formatHitlError(err)))
        .finally(() => setBusyAction(null));
    }

    window.addEventListener('message', onMessage);
    return () => window.removeEventListener('message', onMessage);
    // completeRespond closes over latest card; rebind when the pending challenge changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional: only re-subscribe on challenge
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
    onResolved({ card: result.resolve.card, resumed: result.resumed, revision: result.revision });
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
  // Big Tech / Cloudscape: show consequence, not ops floats. Numeric risk stays
  // server-side for TTL/escalation; UI only surfaces a qualitative chip when high.
  const showElevatedRisk = (isTool || isReview) && local.risk_score >= 0.7;
  const showMeta = !isChoice && (showElevatedRisk || pending);

  return (
    <section
      className={`hitl-card status-${local.status}${purposeClass ? ` ${purposeClass}` : ''}`}
      aria-live="polite"
    >
      <header className="hitl-header">
        <Mark size={18} className="hitl-mark" />
        <div>
          <p className="hitl-kicker">
            {isChoice
              ? t('hitl.kicker.choice')
              : isTool
                ? t('hitl.kicker.tool')
                : t('hitl.kicker.review')}
          </p>
          <h3>{local.title}</h3>
          {local.body &&
            local.body.split('\n\n').map((paragraph, index) => (
              <p key={index} className={index > 0 ? 'hitl-quote' : undefined}>
                {paragraph}
              </p>
            ))}
          {isChoice && pending && <p className="hitl-choice-hint">{t('hitl.choiceHint')}</p>}
        </div>
      </header>

      {showMeta ? (
        <div className="hitl-meta">
          {showElevatedRisk ? (
            <span className="hitl-risk-chip">{t('hitl.riskElevated')}</span>
          ) : null}
          {pending ? (
            <span>{t('hitl.expires', { time: formatDateTime(local.expires_at) })}</span>
          ) : (
            <span className="hitl-status">{hitlStatusLabel(local.status)}</span>
          )}
        </div>
      ) : null}

      {stepUpPending ? (
        <div className="hitl-step-up-form" role="group" aria-label={t('hitl.stepUpGroup')}>
          <p className="hitl-step-up-hint">
            {stepUpPending.challenge.authorize_url
              ? t('hitl.stepUpIdpOpened')
              : t('hitl.stepUpPaste')}
          </p>
          {!stepUpPending.challenge.authorize_url ? (
            <textarea
              className="hitl-step-up-input"
              rows={3}
              value={stepUpAssertion}
              onChange={event => setStepUpAssertion(event.target.value)}
              placeholder={t('hitl.stepUpPlaceholder')}
              disabled={busyAction !== null}
            />
          ) : null}
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
                <span>{t('hitl.stepUpOpenIdp')}</span>
              </button>
            ) : (
              <button
                type="button"
                className="action-card action-primary"
                disabled={busyAction !== null}
                onClick={() => void submitIdpAssertion()}
              >
                <span>{busyAction ? t('hitl.stepUpConfirming') : t('hitl.stepUpSubmit')}</span>
              </button>
            )}
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
              {optionLeading(option)}
              <span>
                {busyAction === option.action_id
                  ? hitlBusyLabel(local.purpose, stepUpPending !== null)
                  : option.label}
              </span>
            </button>
          ))}
        </div>
      ) : (
        <p className="hitl-resolved">{resolvedLabel(local.resolved_action_id, local.status)}</p>
      )}
      {error && <p className="msg-error">{error}</p>}
    </section>
  );
}

function resolvedLabel(
  actionId: string | null | undefined,
  status: HITLCardView['status']
): string {
  if (actionId === 'approve') return t('hitl.resolved.approved');
  if (actionId === 'reject') return t('hitl.resolved.rejected');
  if (status === 'expired' || status === 'auto_rejected' || status === 'dead_letter') {
    return hitlStatusLabel(status);
  }
  if (status === 'escalated') return hitlStatusLabel(status);
  return t('hitl.resolved.done');
}
