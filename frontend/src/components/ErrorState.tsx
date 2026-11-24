export interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
}

export function ErrorState({ title = '加载失败', message, onRetry }: ErrorStateProps) {
  return (
    <div className="state state--error" role="alert">
      <p className="state-title">{title}</p>
      <p className="state-hint mono">{message}</p>
      {onRetry === undefined ? null : (
        <button type="button" className="button" onClick={onRetry}>
          重试
        </button>
      )}
    </div>
  );
}
