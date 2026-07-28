import type { Confidence } from "./types";

export function formatTs(ts: number): string {
  const d = new Date(ts * 1000);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function formatTsFull(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

export function confidenceLabel(confidence: Confidence, agent: string): string {
  // chronicle's own bookkeeping (safety snapshots, restores) isn't a guess --
  // we know exactly who did it. "unknown" here would misleadingly suggest
  // otherwise, right next to a kind badge that already says RESTORE.
  if (agent === "chronicle") return "system";
  switch (confidence) {
    case "hook":
      return "hook";
    case "wrapper":
      return "wrapper";
    case "process":
      return "process (guess)";
    default:
      return agent === "human" ? "human" : "unknown";
  }
}

export function snapshotLabel(prompt: string | null, fileCount: number): string {
  if (prompt) return prompt;
  if (fileCount === 0) return "no file changes";
  return `${fileCount} file${fileCount === 1 ? "" : "s"} changed`;
}
