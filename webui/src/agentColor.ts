// Categorical hue slots are assigned in first-seen order, never cycled or
// re-sorted -- an agent keeps its color for the life of the session once
// assigned. `human` and `unknown` never consume a slot: they aren't
// competing identities, they're the "no agent" / "can't tell" states, and
// get the fixed muted-ink treatment instead (see webui/DESIGN.md). `chronicle`
// itself (the safety/restore snapshots the tool takes) is the same kind of
// non-competing case -- it's not a coding agent whose work you're trying to
// tell apart from others, it's the tool's own bookkeeping.
const SLOT_COUNT = 8;
const NON_AGENTS = new Set(["human", "unknown", "chronicle"]);

export function buildAgentColorMap(agentNamesInFirstSeenOrder: string[]): Map<string, string> {
  const map = new Map<string, string>();
  let slot = 1;
  for (const name of agentNamesInFirstSeenOrder) {
    if (NON_AGENTS.has(name) || map.has(name)) continue;
    map.set(name, `var(--agent-${((slot - 1) % SLOT_COUNT) + 1})`);
    slot++;
  }
  return map;
}

export function colorForAgent(agent: string, colorMap: Map<string, string>): string {
  if (NON_AGENTS.has(agent)) return "var(--ink-muted)";
  return colorMap.get(agent) ?? "var(--ink-muted)";
}

export function isKnownAgent(agent: string): boolean {
  return !NON_AGENTS.has(agent);
}
