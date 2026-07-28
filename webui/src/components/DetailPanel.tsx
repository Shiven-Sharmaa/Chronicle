import { useEffect, useState } from "react";
import type { Snapshot } from "../types";
import { api } from "../api";
import { ConfidenceDot } from "./ConfidenceDot";
import { colorForAgent } from "../agentColor";
import { confidenceLabel, formatTsFull } from "../format";
import { DiffView } from "./DiffView";

interface Props {
  snapshot: Snapshot;
  colorMap: Map<string, string>;
  onClose: () => void;
  onUndo: (snapshot: Snapshot) => Promise<void>;
}

export function DetailPanel({ snapshot, colorMap, onClose, onUndo }: Props) {
  const [diff, setDiff] = useState<string | null>(null);
  const [loadingDiff, setLoadingDiff] = useState(true);
  const [undoing, setUndoing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setDiff(null);
    setLoadingDiff(true);
    api
      .snapshotDiff(snapshot.id)
      .then((r) => {
        if (!cancelled) setDiff(r.diff);
      })
      .catch(() => {
        if (!cancelled) setDiff("");
      })
      .finally(() => {
        if (!cancelled) setLoadingDiff(false);
      });
    return () => {
      cancelled = true;
    };
  }, [snapshot.id]);

  const isChronicleAction = snapshot.kind !== "capture";

  async function handleUndo() {
    setUndoing(true);
    try {
      await onUndo(snapshot);
    } finally {
      setUndoing(false);
    }
  }

  return (
    <aside className="detail-panel" aria-label="Snapshot detail">
      <div className="detail-header">
        <button className="close-button" onClick={onClose} aria-label="Close detail panel">
          &times;
        </button>
        <div className="detail-title">
          <ConfidenceDot agent={snapshot.agent} confidence={snapshot.confidence} colorMap={colorMap} size={12} />
          <span style={{ color: colorForAgent(snapshot.agent, colorMap) }}>{snapshot.agent}</span>
          <span className="muted">&middot; {confidenceLabel(snapshot.confidence, snapshot.agent)}</span>
        </div>
        <div className="muted font-data">{formatTsFull(snapshot.ts)}</div>
      </div>

      {snapshot.prompt_text && <p className="detail-prompt">&ldquo;{snapshot.prompt_text}&rdquo;</p>}

      <dl className="detail-meta">
        {snapshot.tool && (
          <>
            <dt>Tool</dt>
            <dd>{snapshot.tool}</dd>
          </>
        )}
        <dt>Snapshot</dt>
        <dd className="font-data">#{snapshot.id}</dd>
        {snapshot.restored_from_id != null && (
          <>
            <dt>Restored from</dt>
            <dd className="font-data">#{snapshot.restored_from_id}</dd>
          </>
        )}
      </dl>

      {snapshot.files.length > 0 && (
        <ul className="detail-files font-data">
          {snapshot.files.map((f) => (
            <li key={f.path}>
              <span className="file-change-type">{f.change_type}</span> {f.path}{" "}
              <span className="stat-add">+{f.added}</span> <span className="stat-remove">-{f.removed}</span>
            </li>
          ))}
        </ul>
      )}

      <div className="detail-diff">
        {loadingDiff ? <p className="muted">Loading diff...</p> : <DiffView diff={diff ?? ""} />}
      </div>

      {!isChronicleAction && (
        <div className="detail-actions">
          <button className="primary-button" onClick={handleUndo} disabled={undoing}>
            {undoing ? "Undoing..." : "Undo this change"}
          </button>
          <p className="muted small">
            Takes a safety snapshot first, so this can always be undone too.
          </p>
        </div>
      )}
    </aside>
  );
}
