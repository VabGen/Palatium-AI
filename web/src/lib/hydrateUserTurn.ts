/**
 * Map a persisted user dialog turn into ChatShell message fields.
 *
 * Live send stores ``attachmentIds`` + ``attachmentNames`` in memory; the API
 * only persists ``payload.attachment_ids`` (and optional ``attachment_names``).
 * Hydrate must rebuild both or file chips disappear after a thread switch.
 */
import { fetchAttachment } from '../api/client';
import { displayTextForUserTurn } from './hitlResume';

export type HydratedUserTurn = {
  text: string;
  attachmentIds: string[];
  attachmentNames: string[];
};

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  const out: string[] = [];
  for (const item of value) {
    if (typeof item !== 'string') continue;
    const trimmed = item.trim();
    if (trimmed) out.push(trimmed);
  }
  return out;
}

/** UUID refs from ``payload.attachment_ids`` (list or comma-separated string). */
export function attachmentIdsFromPayload(
  payload: Record<string, unknown> | null | undefined
): string[] {
  if (!payload) return [];
  const raw = payload.attachment_ids;
  if (typeof raw === 'string') {
    return raw
      .split(',')
      .map(part => part.trim())
      .filter(Boolean);
  }
  return stringList(raw);
}

/** Optional display names already stored on the turn (historyPreview path). */
export function attachmentNamesFromPayload(
  payload: Record<string, unknown> | null | undefined
): string[] {
  if (!payload) return [];
  const direct = stringList(payload.attachment_names);
  if (direct.length > 0) return direct;
  const attachments = payload.attachments;
  if (!Array.isArray(attachments)) return [];
  const names: string[] = [];
  for (const item of attachments) {
    if (!item || typeof item !== 'object' || Array.isArray(item)) continue;
    const row = item as Record<string, unknown>;
    const name =
      typeof row.filename === 'string'
        ? row.filename.trim()
        : typeof row.name === 'string'
          ? row.name.trim()
          : '';
    if (name) names.push(name);
  }
  return names;
}

async function resolveMissingNames(
  ids: string[],
  knownNames: string[],
  userId?: string | null,
  orgId?: string | null
): Promise<string[]> {
  if (ids.length === 0) return knownNames;
  if (knownNames.length === ids.length) return knownNames;
  const resolved = await Promise.all(
    ids.map(async (id, index) => {
      const known = knownNames[index]?.trim();
      if (known) return known;
      try {
        const row = await fetchAttachment(id, userId, orgId);
        return row.filename.trim() || id;
      } catch {
        return id;
      }
    })
  );
  return resolved;
}

export async function hydrateUserTurn(
  content: string,
  payload: Record<string, unknown> | null | undefined,
  userId?: string | null,
  orgId?: string | null
): Promise<HydratedUserTurn> {
  const attachmentIds = attachmentIdsFromPayload(payload);
  const knownNames = attachmentNamesFromPayload(payload);
  const attachmentNames =
    attachmentIds.length > 0
      ? await resolveMissingNames(attachmentIds, knownNames, userId, orgId)
      : knownNames;
  return {
    text: displayTextForUserTurn(content),
    attachmentIds,
    attachmentNames,
  };
}
