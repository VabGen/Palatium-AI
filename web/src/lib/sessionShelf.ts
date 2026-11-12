/**
 * P1b / P2 — map durable `/sessions` rows onto History shelf items.
 */

export type SessionShelfSource = {
  thread_id: string;
  title?: string | null;
  project_id?: string | null;
  updated_at?: string | null;
};

export type SessionShelfItem = {
  id: string;
  title: string;
  projectId?: string | null;
  /** ISO timestamp — chat-history date groups (absent rows fall back to "Earlier"). */
  updatedAt?: string;
};

export function mapSessionsToShelf(
  sessions: readonly SessionShelfSource[],
  untitled: string
): SessionShelfItem[] {
  const seen = new Set<string>();
  const out: SessionShelfItem[] = [];
  for (const session of sessions) {
    const id = session.thread_id.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    const title = session.title?.trim();
    const updatedAt = session.updated_at ?? undefined;
    out.push({
      id,
      title: title && title.length > 0 ? title : untitled,
      projectId: session.project_id ?? null,
      updatedAt,
    });
  }
  return out;
}

/** Merge API shelf with the live thread (may not be persisted yet). */
export function mergeShelfWithLiveThread(
  shelf: readonly SessionShelfItem[],
  liveThreadId: string,
  liveTitle: string,
  liveProjectId?: string | null
): SessionShelfItem[] {
  const byId = new Map<string, SessionShelfItem>();
  for (const item of shelf) byId.set(item.id, item);
  const prior = byId.get(liveThreadId);
  byId.set(liveThreadId, {
    id: liveThreadId,
    title: liveTitle,
    projectId: liveProjectId !== undefined ? liveProjectId : (prior?.projectId ?? null),
    updatedAt: prior?.updatedAt,
  });
  const ordered = [liveThreadId, ...[...byId.keys()].filter(id => id !== liveThreadId)];
  return ordered.map(id => byId.get(id) ?? { id, title: liveTitle, projectId: null });
}

/** Group shelf threads under project folders; unpinned last. */
export function groupShelfByProject(
  threads: readonly SessionShelfItem[],
  projects: readonly { id: string; title: string }[]
): { projectId: string | null; title: string; threads: SessionShelfItem[] }[] {
  const titleById = new Map(projects.map(p => [p.id, p.title]));
  const buckets = new Map<string | null, SessionShelfItem[]>();
  for (const thread of threads) {
    const key = thread.projectId?.trim() || null;
    const list = buckets.get(key) ?? [];
    list.push(thread);
    buckets.set(key, list);
  }
  const groups: { projectId: string | null; title: string; threads: SessionShelfItem[] }[] = [];
  for (const project of projects) {
    const threadsIn = buckets.get(project.id);
    if (threadsIn?.length) {
      groups.push({ projectId: project.id, title: project.title, threads: threadsIn });
      buckets.delete(project.id);
    }
  }
  for (const [projectId, threadsIn] of buckets) {
    if (projectId === null) continue;
    groups.push({
      projectId,
      title: titleById.get(projectId) ?? projectId.slice(0, 8),
      threads: threadsIn,
    });
  }
  const unpinned = buckets.get(null);
  if (unpinned?.length) {
    groups.push({ projectId: null, title: '', threads: unpinned });
  }
  return groups;
}
