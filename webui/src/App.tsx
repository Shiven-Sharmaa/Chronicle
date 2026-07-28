import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import type { AgentCount, Snapshot } from "./types";
import { buildAgentColorMap } from "./agentColor";
import { Sidebar, type DateRangePreset } from "./components/Sidebar";
import { Timeline } from "./components/Timeline";
import { DetailPanel } from "./components/DetailPanel";
import { Blame } from "./components/Blame";
import { Toast } from "./components/Toast";

const POLL_MS = 3000;

function sinceTsFor(preset: DateRangePreset): number | null {
  const now = Date.now() / 1000;
  switch (preset) {
    case "1h":
      return now - 3600;
    case "24h":
      return now - 86400;
    case "7d":
      return now - 7 * 86400;
    default:
      return null;
  }
}

export default function App() {
  const [tab, setTab] = useState<"timeline" | "blame">("timeline");
  const [snapshotCount, setSnapshotCount] = useState(0);
  const [agentCounts, setAgentCounts] = useState<AgentCount[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);
  const [fileFilter, setFileFilter] = useState("");
  const [dateRange, setDateRange] = useState<DateRangePreset>("all");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const colorMap = useMemo(() => buildAgentColorMap(agentCounts.map((a) => a.agent)), [agentCounts]);

  const refresh = useCallback(async () => {
    const [status, agents, snaps] = await Promise.all([
      api.status(),
      api.agents(),
      api.snapshots({
        agent: selectedAgent,
        file: fileFilter.trim() || null,
        sinceTs: sinceTsFor(dateRange),
      }),
    ]);
    setSnapshotCount(status.snapshot_count);
    setAgentCounts(agents);
    setSnapshots(snaps);
  }, [selectedAgent, fileFilter, dateRange]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, POLL_MS);
    return () => clearInterval(id);
  }, [refresh]);

  useEffect(() => {
    api.files().then(setFiles).catch(() => {});
  }, [snapshotCount]);

  const selected = snapshots.find((s) => s.id === selectedId) ?? null;

  async function handleUndo(snapshot: Snapshot) {
    await api.restore(snapshot.id);
    setToast("Change undone.");
    setSelectedId(null);
    await refresh();
  }

  return (
    <div className="app-shell">
      <button
        className="mobile-nav-toggle"
        onClick={() => setSidebarOpen((v) => !v)}
        aria-expanded={sidebarOpen}
        aria-controls="sidebar"
      >
        &#9776; Filters
      </button>
      <div className={sidebarOpen ? "sidebar-slot open" : "sidebar-slot"} id="sidebar">
        <Sidebar
          tab={tab}
          onTabChange={(t) => {
            setTab(t);
            setSidebarOpen(false);
            setSelectedId(null);
          }}
          agentCounts={agentCounts}
          colorMap={colorMap}
          selectedAgent={selectedAgent}
          onAgentChange={setSelectedAgent}
          fileFilter={fileFilter}
          onFileFilterChange={setFileFilter}
          dateRange={dateRange}
          onDateRangeChange={setDateRange}
          snapshotCount={snapshotCount}
        />
      </div>

      <main className="main-column">
        {tab === "timeline" ? (
          <Timeline
            snapshots={snapshots}
            colorMap={colorMap}
            selectedId={selectedId}
            onSelect={setSelectedId}
          />
        ) : (
          <Blame colorMap={colorMap} files={files} />
        )}
      </main>

      {selected && (
        <DetailPanel
          snapshot={selected}
          colorMap={colorMap}
          onClose={() => setSelectedId(null)}
          onUndo={handleUndo}
        />
      )}

      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  );
}
