import { fetchHitlCard } from '../api/client';
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

export function formatHitlError(err: unknown): string {
  const message = err instanceof Error ? err.message : String(err);
  if (message.includes('409')) return 'This card was already answered.';
  if (message.includes('410')) return 'This card has expired.';
  if (message.includes('403')) return 'You are not allowed to act on this card.';
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
  return {
    document: result.output,
    hitlCards,
    _requiresReview: requiresReview,
    _pendingReview: requiresReview && result.output === null && !hasHitl,
    error: result.error ?? undefined,
    status: result.status,
  };
}
