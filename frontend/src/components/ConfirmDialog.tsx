import { useState } from 'react';

export interface ConfirmDialogProps {
  title: string;
  lines: string[];
  confirmLabel: string;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}

/** One small gate for destructive actions; never fires without an explicit click. */
export function ConfirmDialog({ title, lines, confirmLabel, onCancel, onConfirm }: ConfirmDialogProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-label={title}>
      <div className="dialog dialog--narrow">
        <header className="dialog-head">
          <h2>{title}</h2>
          <button type="button" className="link-button" onClick={onCancel} aria-label="关闭">×</button>
        </header>
        <ul className="dialog-warnings">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        {error && <p className="action-message" role="alert">{error}</p>}
        <footer className="dialog-foot">
          <button type="button" className="button button--ghost" onClick={onCancel}>取消</button>
          <button
            type="button"
            className="button"
            disabled={busy}
            onClick={() => {
              setBusy(true);
              setError('');
              void onConfirm()
                .catch((caught: unknown) => setError(caught instanceof Error ? caught.message : String(caught)))
                .finally(() => setBusy(false));
            }}
          >
            {busy ? '处理中…' : confirmLabel}
          </button>
        </footer>
      </div>
    </div>
  );
}
