interface Props {
  title: string;
  hint?: string;
}

export function EmptyState({ title, hint }: Props) {
  return (
    <div className="empty-state">
      <p>{title}</p>
      {hint && <p className="muted">{hint}</p>}
    </div>
  );
}
