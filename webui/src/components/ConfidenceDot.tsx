import type { Confidence } from "../types";
import { colorForAgent } from "../agentColor";

interface Props {
  agent: string;
  confidence: Confidence;
  colorMap: Map<string, string>;
  size?: number;
}

/**
 * The one recurring glyph that answers "how sure are we": solid = confident
 * (hook/wrapper), dashed ring = a guess (process), hollow = no signal
 * (human/unknown). Color (separately) answers "which agent." Always meant
 * to be rendered next to a visible text label -- never alone.
 */
export function ConfidenceDot({ agent, confidence, colorMap, size = 10 }: Props) {
  const color = colorForAgent(agent, colorMap);
  const base = {
    width: size,
    height: size,
    borderRadius: "50%",
    display: "inline-block",
    flexShrink: 0,
    boxSizing: "border-box" as const,
  };

  if (confidence === "hook" || confidence === "wrapper") {
    return <span style={{ ...base, background: color }} />;
  }
  if (confidence === "process") {
    return (
      <span
        style={{
          ...base,
          background: color,
          opacity: 0.55,
          border: `1.5px dashed ${color}`,
        }}
      />
    );
  }
  // confidence === "none" or null -- human or unknown, no hue.
  const dashed = agent === "unknown";
  return (
    <span
      style={{
        ...base,
        background: "transparent",
        border: dashed ? "1.5px dashed var(--ink-muted)" : "1.5px solid var(--ink-muted)",
      }}
    />
  );
}
