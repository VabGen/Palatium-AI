import { ApiError, fetchHitlCard } from '../api/client';
import { t } from '../i18n';
import type { FormatterTaskResult, HITLCardView } from '../types/contentDocument';

export function pendingHitlCards(cards: HITLCardView[] | null | undefined): HITLCardView[] {
  return (cards ?? []).filter(card => card.status === 'pending');
}

export function cardNeedsTokenRefresh(card: HITLCardView): boolean {
  return card.status === 'pending' && card.options.some(option => !option.action_token?.trim());
}

export async function hydratePendingHitlCards(
  cards: HITLCardView[],
  userId?: string | null,
  orgId?: string | null
): Promise<HITLCardView[]> {
  if (cards.length === 0) return cards;
  const refreshed = await Promise.all(
    cards.map(async card => {
      if (!cardNeedsTokenRefresh(card)) return card;
      try {
        return await fetchHitlCard(card.card_id, userId, orgId);
      } catch {
        return card;
      }
    })
  );
  const byId = new Map(refreshed.map(card => [card.card_id, card]));
  return cards.map(card => byId.get(card.card_id) ?? card);
}

/**
 * Human-readable HITL failure.
 *
 * Решение принимается по СТАТУСУ (`ApiError`), а не по подстроке в тексте: сервер
 * вправе вернуть `detail: "card expired"` без кода внутри, и тогда разбор по «410»
 * молча перестаёт работать. Отдельный текст на каждый код нужен потому, что
 * последствия у них разные: карточка уже отвечена, истекла или недоступна роли.
 */
export function formatHitlError(err: unknown): string {
  if (err instanceof ApiError) {
    switch (err.status) {
      case 403:
        return t('hitl.error.forbidden');
      case 409:
        return t('hitl.error.alreadyAnswered');
      case 410:
        return t('hitl.error.expired');
      default:
        return err.message.slice(0, 400);
    }
  }
  const message = err instanceof Error ? err.message : String(err);
  return message.slice(0, 400);
}

export type AssistantMessageFields = {
  document: FormatterTaskResult['output'];
  hitlCards: HITLCardView[];
  _requiresReview: boolean;
  _pendingReview: boolean;
  error?: string;
  status: FormatterTaskResult['status'];
};

export function fieldsFromFormatterResult(result: FormatterTaskResult): AssistantMessageFields {
  const hitlCards = pendingHitlCards(result.hitl_cards);
  const requiresReview = Boolean(result.requires_review);
  const hasHitl = hitlCards.length > 0;
  const document = result.output;
  const emptyFailure = document === null && !hasHitl;
  return {
    document,
    hitlCards,
    _requiresReview: requiresReview,
    // Never a contentless "moderator" wait: HITL is cards on a draft, else it's a failure.
    _pendingReview: false,
    error: emptyFailure
      ? result.error?.trim() || t('msg.emptyResponse')
      : (result.error ?? undefined),
    status: emptyFailure ? 'failure' : result.status,
  };
}
