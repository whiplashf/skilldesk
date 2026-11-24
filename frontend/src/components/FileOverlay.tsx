import { useEffect, useMemo, useRef } from 'react';
import type { FileContent } from '../api/types';
import { api } from '../api/endpoints';
import { formatBytes } from '../lib/format';
import { resolveAssetSources } from '../lib/html';
import { fileKindLabel } from '../lib/labels';
import { useApi } from '../lib/useApi';
import { ErrorState } from './ErrorState';
import { Skeleton } from './Skeleton';

export interface FileOverlayProps {
  skillKey: string;
  rel: string;
  onClose: () => void;
}

function MarkdownBody({ html, identityKey }: { html: string; identityKey: string }) {
  const resolved = useMemo(() => resolveAssetSources(html, identityKey), [html, identityKey]);
  return <div className="prose" dangerouslySetInnerHTML={{ __html: resolved }} />;
}

function FileBody({ file, identityKey }: { file: FileContent; identityKey: string }) {
  if (file.kind === 'image') {
    return file.url === undefined ? (
      <p className="block-note">图片没有可用的原始地址。</p>
    ) : (
      <img className="overlay-image" src={file.url} alt={file.name} />
    );
  }

  if (file.kind === 'markdown') {
    return file.html === undefined ? (
      <p className="block-note">该 Markdown 没有渲染结果。</p>
    ) : (
      <MarkdownBody html={file.html} identityKey={identityKey} />
    );
  }

  if (file.kind === 'text') {
    return file.text === undefined ? (
      <p className="block-note">该文本文件没有内容。</p>
    ) : (
      <pre className="overlay-text mono">{file.text}</pre>
    );
  }

  return (
    <div className="state">
      <p className="state-title">二进制文件不提供预览</p>
      <p className="state-hint mono">{file.path}</p>
    </div>
  );
}

export function FileOverlay({ skillKey, rel, onClose }: FileOverlayProps) {
  const file = useApi<FileContent>((signal) => api.file(skillKey, rel, signal), [skillKey, rel]);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const previous = document.activeElement;
    closeRef.current?.focus();
    return () => {
      if (previous instanceof HTMLElement) {
        previous.focus();
      }
    };
  }, []);

  return (
    <div className="overlay" onClick={onClose}>
      <div
        className="overlay-panel"
        role="dialog"
        aria-modal="true"
        aria-label={`支持文件 ${rel}`}
        onClick={(event) => {
          event.stopPropagation();
        }}
      >
        <header className="overlay-head">
          <div className="overlay-title">
            <span className="overlay-name mono">{file.state.status === 'ready' ? file.state.data.name : rel}</span>
            <span className="overlay-sub mono">{rel}</span>
          </div>
          <div className="overlay-meta">
            {file.state.status === 'ready' ? (
              <>
                <span className="chip">{fileKindLabel(file.state.data.kind)}</span>
                <span className="chip mono">{formatBytes(file.state.data.size)}</span>
              </>
            ) : null}
            <button ref={closeRef} type="button" className="icon-button" aria-label="关闭预览" title="关闭（Esc）" onClick={onClose}>
              ×
            </button>
          </div>
        </header>

        <div className="overlay-body">
          {file.state.status === 'loading' ? (
            <div className="file-skeleton" aria-hidden="true">
              <Skeleton width="48%" height={13} />
              <Skeleton height={11} />
              <Skeleton width="82%" height={11} />
              <Skeleton width="66%" height={11} />
            </div>
          ) : null}
          {file.state.status === 'error' ? (
            <ErrorState title="文件加载失败" message={file.state.error} onRetry={file.reload} />
          ) : null}
          {file.state.status === 'ready' ? <FileBody file={file.state.data} identityKey={skillKey} /> : null}
        </div>
      </div>
    </div>
  );
}
