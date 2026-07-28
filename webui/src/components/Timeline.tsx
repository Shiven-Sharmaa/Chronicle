import { useLayoutEffect, useRef, useState } from "react";
import type { Snapshot } from "../types";
import { ConfidenceDot } from "./ConfidenceDot";
import { colorForAgent } from "../agentColor";
import { confidenceLabel, formatTs, snapshotLabel } from "../format";
import { EmptyState } from "./EmptyState";

interface Props {
  snapshots: Snapshot[];
  colorMap: Map<string, string>;
  selectedId: number | null;
  onSelect: (id: number) => void;
}

interface ConnectorPath {
  id: string;
  d: string;
}

/**
 * The spine: a vertical hairline through every snapshot in order, each one
 * a node on it. A `restore` node additionally curves a dashed connector
 * back to the snapshot it restored -- the one place this is genuinely a
 * graph rather than a list (see DESIGN.md).
 */
export function Timeline({ snapshots, colorMap, selectedId, onSelect }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const rowRefs = useRef<Map<number, HTMLElement>>(new Map());
  const [connectors, setConnectors] = useState<ConnectorPath[]>([]);

  useLayoutEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const containerRect = container.getBoundingClientRect();
    const next: ConnectorPath[] = [];

    for (const s of snapshots) {
      if (s.kind !== "restore" || s.restored_from_id == null) continue;
      const fromEl = rowRefs.current.get(s.id);
      const toEl = rowRefs.current.get(s.restored_from_id);
      if (!fromEl || !toEl) continue; // target filtered out of view

      const fromRect = fromEl.getBoundingClientRect();
      const toRect = toEl.getBoundingClientRect();
      const x = 15.5;
      const fromY = fromRect.top - containerRect.top + fromRect.height / 2;
      const toY = toRect.top - containerRect.top + toRect.height / 2;
      const bulge = x + 26;
      const d = `M ${x} ${fromY} C ${bulge} ${fromY}, ${bulge} ${toY}, ${x} ${toY}`;
      next.push({ id: `${s.id}`, d });
    }
    setConnectors(next);
  }, [snapshots]);

  if (snapshots.length === 0) {
    return (
      <EmptyState
        title="No changes recorded yet."
        hint="Start your agent and they'll appear here."
      />
    );
  }

  return (
    <div className="timeline" ref={containerRef}>
      <svg className="timeline-connectors" aria-hidden="true">
        {connectors.map((c) => (
          <path key={c.id} d={c.d} />
        ))}
      </svg>
      <ol className="timeline-list">
        {snapshots.map((s) => (
          <li
            key={s.id}
            ref={(el) => {
              if (el) rowRefs.current.set(s.id, el);
              else rowRefs.current.delete(s.id);
            }}
          >
            <button
              className={s.id === selectedId ? "timeline-node selected" : "timeline-node"}
              onClick={() => onSelect(s.id)}
              aria-current={s.id === selectedId}
            >
              <span className="node-dot">
                <ConfidenceDot agent={s.agent} confidence={s.confidence} colorMap={colorMap} size={12} />
              </span>
              <span className="node-body">
                <span className="node-line1">
                  <span className="node-agent" style={{ color: colorForAgent(s.agent, colorMap) }}>
                    {s.agent}
                  </span>
                  <span className="node-confidence muted">
                    {confidenceLabel(s.confidence, s.agent)}
                  </span>
                  {s.kind !== "capture" && <span className="node-kind">{s.kind}</span>}
                  <span className="node-ts font-data muted">{formatTs(s.ts)}</span>
                </span>
                <span className="node-line2 muted">
                  {snapshotLabel(s.prompt_text, s.files.length)}
                  {s.files.length > 0 && (
                    <span className="node-stat font-data">
                      {" "}
                      <span className="stat-add">+{s.added_total}</span>{" "}
                      <span className="stat-remove">-{s.removed_total}</span>
                    </span>
                  )}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
