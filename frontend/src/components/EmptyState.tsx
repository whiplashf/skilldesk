export interface EmptyStateProps {
  title: string;
  hint?: string;
  actionLabel?: string;
  onAction?: () => void;
  actionHref?: string;
}

export function EmptyState({ title, hint, actionLabel, onAction, actionHref }: EmptyStateProps) {
  return (
    <div className="state">
      <p className="state-title">{title}</p>
      {hint === undefined ? null : <p className="state-hint">{hint}</p>}
      {actionLabel === undefined ? null : actionHref !== undefined ? (
        <a className="button" href={actionHref}>
          {actionLabel}
        </a>
      ) : onAction === undefined ? null : (
        <button type="button" className="button" onClick={onAction}>
          {actionLabel}
        </button>
      )}
    </div>
  );
}
