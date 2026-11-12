/**
 * Big Tech answer share: Web Share API when available, else clipboard.
 * No permanent share-URL product yet — text payload is the portable unit.
 */

export type ShareAnswerResult = 'shared' | 'copied' | 'failed';

export async function shareAnswerText(params: {
  title: string;
  text: string;
}): Promise<ShareAnswerResult> {
  const body = params.text.trim();
  if (!body) return 'failed';

  const canShare =
    typeof navigator !== 'undefined' &&
    typeof navigator.share === 'function' &&
    (!navigator.canShare || navigator.canShare({ text: body, title: params.title }));

  if (canShare) {
    try {
      await navigator.share({ title: params.title, text: body });
      return 'shared';
    } catch (error) {
      // User dismisses the sheet — not a failure toast case.
      if (error instanceof DOMException && error.name === 'AbortError') {
        return 'failed';
      }
    }
  }

  try {
    await navigator.clipboard.writeText(body);
    return 'copied';
  } catch {
    return 'failed';
  }
}
