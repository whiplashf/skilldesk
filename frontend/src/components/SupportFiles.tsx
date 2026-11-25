import { api } from '../api/endpoints';
import { formatBytes } from '../lib/format';
import { fileKindLabel } from '../lib/labels';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { Skeleton } from './Skeleton';

export interface SupportFilesProps {
  identityKey: string;
  generation: string;
  onOpenFile: (rel: string) => void;
}

export function SupportFiles({ identityKey, generation, onOpenFile }: SupportFilesProps) {
  const { state, reload: onRetry } = useApi(signal => api.files(identityKey, signal), [identityKey, generation], true);
  return (
    <section className="block">

      {state.status === 'loading' ? (
        <div className="file-skeleton" aria-hidden="true">
          <Skeleton width="52%" height={11} />
          <Skeleton width="38%" height={11} />
          <Skeleton width="64%" height={11} />
        </div>
      ) : null}

      {state.status === 'error' ? <ErrorState title="支持文件加载失败" message={state.error} onRetry={onRetry} /> : null}

      {state.status === 'ready' && state.data.items.length === 0 ? (
        <p className="block-note">该 skill 没有支持文件。</p>
      ) : null}

      {state.status === 'ready' && state.data.items.length > 0 ? (
        <ul className="files">
          {state.data.items.map((file) => (
            <li key={file.rel}>
              <button
                type="button"
                className="file"
                title={`预览 ${file.rel}`}
                onClick={() => {
                  onOpenFile(file.rel);
                }}
              >
                <span className="file-rel mono">{file.rel}</span>
                <span className="file-meta">
                  {fileKindLabel(file.kind)}
                  <span className="file-size mono">{formatBytes(file.size)}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
