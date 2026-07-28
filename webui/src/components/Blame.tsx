import { useEffect, useState } from "react";
import { api } from "../api";
import type { BlameLine } from "../types";
import { ConfidenceDot } from "./ConfidenceDot";
import { colorForAgent } from "../agentColor";
import { EmptyState } from "./EmptyState";

interface Props {
  colorMap: Map<string, string>;
  files: string[];
}

export function Blame({ colorMap, files }: Props) {
  const [path, setPath] = useState("");
  const [lines, setLines] = useState<BlameLine[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!path.trim()) {
      setLines(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .blame(path.trim())
      .then((r) => {
        if (!cancelled) setLines(r.lines);
      })
      .catch((e) => {
        if (!cancelled) {
          setLines(null);
          setError(e.message || "no history for this file");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [path]);

  return (
    <div className="blame-view">
      <div className="blame-search">
        <input
          type="search"
          list="blame-files"
          placeholder="Path, e.g. src/api.py"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          aria-label="File to blame"
        />
        <datalist id="blame-files">
          {files.map((f) => (
            <option key={f} value={f} />
          ))}
        </datalist>
      </div>

      {!path.trim() && (
        <EmptyState
          title="Pick a file to see who wrote each line."
          hint="Every line is tinted by the agent that last touched it."
        />
      )}
      {loading && <p className="muted">Loading...</p>}
      {error && <p className="muted">{error}</p>}

      {lines && (
        <pre className="blame-lines font-data">
          {lines.map((l) => {
            const color = l.agent ? colorForAgent(l.agent, colorMap) : "var(--ink-muted)";
            return (
              <div className="blame-line" key={l.line} style={{ borderLeftColor: color }}>
                <span className="blame-lineno muted">{l.line}</span>
                <span className="blame-agent">
                  {l.agent && (
                    <ConfidenceDot agent={l.agent} confidence={l.confidence} colorMap={colorMap} size={8} />
                  )}
                  <span className="muted" style={{ color }}>
                    {l.agent ?? "?"}
                  </span>
                </span>
                <span className="blame-content">{l.content}</span>
              </div>
            );
          })}
        </pre>
      )}
    </div>
  );
}
