import type { AgentCount, BlameResult, Snapshot, Status } from "./types";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface SnapshotFilters {
  agent?: string | null;
  file?: string | null;
  sinceTs?: number | null;
}

function qs(params: Record<string, string | number | undefined | null>): string {
  const usp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") usp.set(k, String(v));
  }
  const s = usp.toString();
  return s ? `?${s}` : "";
}

export const api = {
  status: () => req<Status>("/api/status"),

  agents: () => req<AgentCount[]>("/api/agents"),

  files: () => req<string[]>("/api/files"),

  snapshots: (filters: SnapshotFilters = {}) =>
    req<Snapshot[]>(
      `/api/snapshots${qs({
        agent: filters.agent,
        file: filters.file,
        since_ts: filters.sinceTs,
      })}`,
    ),

  snapshot: (id: number) => req<Snapshot>(`/api/snapshots/${id}`),

  snapshotDiff: (id: number) =>
    req<{ commit_sha: string; diff: string }>(`/api/snapshots/${id}/diff`),

  diffBetween: (a: number, b: number) =>
    req<{ diff: string }>(`/api/diff${qs({ a, b })}`),

  restore: (id: number) =>
    req<{ safety_snapshot_id: number; restore_snapshot_id: number }>(
      `/api/snapshots/${id}/restore`,
      { method: "POST" },
    ),

  blame: (path: string, snapshot?: number) =>
    req<BlameResult>(`/api/blame${qs({ path, snapshot })}`),
};
