interface Props {
  diff: string;
}

/** Minimal unified-diff renderer: colorizes +/- lines and dims file/hunk
 * headers. No syntax highlighting -- this is provenance evidence, not a
 * code editor. */
export function DiffView({ diff }: Props) {
  if (!diff.trim()) {
    return <p className="muted">No changes in this diff.</p>;
  }

  const lines = diff.split("\n");
  return (
    <pre className="diff-view font-data">
      {lines.map((line, i) => {
        let cls = "diff-context";
        if (line.startsWith("+++") || line.startsWith("---")) cls = "diff-file-header";
        else if (line.startsWith("@@")) cls = "diff-hunk-header";
        else if (line.startsWith("diff --git") || line.startsWith("index ")) cls = "diff-meta";
        else if (line.startsWith("+")) cls = "diff-add";
        else if (line.startsWith("-")) cls = "diff-remove";
        return (
          <div key={i} className={cls}>
            {line.length ? line : " "}
          </div>
        );
      })}
    </pre>
  );
}
