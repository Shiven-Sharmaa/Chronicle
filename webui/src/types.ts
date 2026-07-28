export type Confidence = "hook" | "wrapper" | "process" | "none" | null;

export interface FileChange {
  path: string;
  change_type: "A" | "M" | "D" | "R";
  added: number;
  removed: number;
}

export interface Snapshot {
  id: number;
  commit_sha: string;
  parent_id: number | null;
  ts: number;
  agent: string;
  session_id: string | null;
  tool: string | null;
  confidence: Confidence;
  kind: "capture" | "restore-safety" | "restore";
  restored_from_id: number | null;
  prompt_text: string | null;
  files: FileChange[];
  added_total: number;
  removed_total: number;
}

export interface AgentCount {
  agent: string;
  count: number;
}

export interface BlameLine {
  line: number;
  content: string;
  agent: string | null;
  confidence: Confidence;
  snapshot_id: number | null;
}

export interface BlameResult {
  path: string;
  lines: BlameLine[];
}

export interface Status {
  root: string;
  snapshot_count: number;
}
