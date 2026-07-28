import type { AgentCount } from "../types";
import { colorForAgent } from "../agentColor";

export type DateRangePreset = "all" | "1h" | "24h" | "7d";

interface Props {
  tab: "timeline" | "blame";
  onTabChange: (tab: "timeline" | "blame") => void;
  agentCounts: AgentCount[];
  colorMap: Map<string, string>;
  selectedAgent: string | null;
  onAgentChange: (agent: string | null) => void;
  fileFilter: string;
  onFileFilterChange: (file: string) => void;
  dateRange: DateRangePreset;
  onDateRangeChange: (preset: DateRangePreset) => void;
  snapshotCount: number;
}

const DATE_PRESETS: { key: DateRangePreset; label: string }[] = [
  { key: "all", label: "All time" },
  { key: "1h", label: "Last hour" },
  { key: "24h", label: "Last 24 hours" },
  { key: "7d", label: "Last 7 days" },
];

export function Sidebar({
  tab,
  onTabChange,
  agentCounts,
  colorMap,
  selectedAgent,
  onAgentChange,
  fileFilter,
  onFileFilterChange,
  dateRange,
  onDateRangeChange,
  snapshotCount,
}: Props) {
  return (
    <nav className="sidebar" aria-label="Filters and views">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true">
          &#9679;
        </span>
        chronicle
      </div>

      <div className="tab-switcher" role="tablist">
        <button
          role="tab"
          aria-selected={tab === "timeline"}
          className={tab === "timeline" ? "tab active" : "tab"}
          onClick={() => onTabChange("timeline")}
        >
          Timeline
        </button>
        <button
          role="tab"
          aria-selected={tab === "blame"}
          className={tab === "blame" ? "tab active" : "tab"}
          onClick={() => onTabChange("blame")}
        >
          Blame
        </button>
      </div>

      {tab === "timeline" && (
        <>
          <section className="filter-group">
            <h3>Agent</h3>
            <ul className="agent-filter-list">
              <li>
                <button
                  className={selectedAgent === null ? "agent-filter active" : "agent-filter"}
                  onClick={() => onAgentChange(null)}
                >
                  <span className="dot-placeholder" aria-hidden="true">
                    &#9673;
                  </span>
                  All agents
                  <span className="count">{snapshotCount}</span>
                </button>
              </li>
              {agentCounts.map((a) => (
                <li key={a.agent}>
                  <button
                    className={selectedAgent === a.agent ? "agent-filter active" : "agent-filter"}
                    onClick={() => onAgentChange(a.agent)}
                  >
                    <span
                      className="agent-swatch"
                      style={{ background: colorForAgent(a.agent, colorMap) }}
                      aria-hidden="true"
                    />
                    {a.agent}
                    <span className="count">{a.count}</span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <section className="filter-group">
            <h3>File</h3>
            <input
              type="search"
              placeholder="src/api.py"
              value={fileFilter}
              onChange={(e) => onFileFilterChange(e.target.value)}
              aria-label="Filter by file path"
            />
          </section>

          <section className="filter-group">
            <h3>Date</h3>
            <ul className="preset-list">
              {DATE_PRESETS.map((p) => (
                <li key={p.key}>
                  <button
                    className={dateRange === p.key ? "preset active" : "preset"}
                    onClick={() => onDateRangeChange(p.key)}
                  >
                    {dateRange === p.key && (
                      <span aria-hidden="true" className="check">
                        &#10003;
                      </span>
                    )}
                    {p.label}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
    </nav>
  );
}
