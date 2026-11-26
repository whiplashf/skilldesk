import { useMemo, useState } from 'react';
import type { GitHubRelease } from '../api/types';
import { formatDateTime } from '../lib/format';

function excerptOf(release: GitHubRelease) {
  let text = release.body;
  if (release.html) {
    const template = document.createElement('template');
    template.innerHTML = release.html;
    const blocks = template.content.querySelectorAll('h1,h2,h3,h4,h5,h6,p,pre,tr');
    text = Array.from(blocks, block => (block.parentElement?.tagName === 'LI' ? '• ' : '') + block.textContent).join('\n');
  }
  const excerpt = text.split('\n').slice(0, 4).join('\n').slice(0, 420).trimEnd();
  return excerpt.length < text.trimEnd().length ? excerpt + '…' : '';
}

export function ReleaseNotes({ release }: { release: GitHubRelease }) {
  const [expanded, setExpanded] = useState(false);
  const excerpt = useMemo(() => excerptOf(release), [release]);
  const published = Date.parse(release.publishedAt);
  return <div className="release-notes">
    <div className="release-notes-heading"><strong>仓库发布说明</strong>
      {Number.isFinite(published) && <time dateTime={release.publishedAt}>{formatDateTime(published / 1000).slice(0, 10)}</time>}
      <a href={release.url} target="_blank" rel="noreferrer">GitHub 原文 ↗</a>
    </div>
    {release.title && release.title !== release.tag && <p className="release-title">{release.title}</p>}
    {release.body ? <>{!expanded && excerpt
      ? <div className="release-body">{excerpt}</div>
      : release.html ? <div className="release-body release-markdown" dangerouslySetInnerHTML={{ __html: release.html }} />
      : <div className="release-body">{release.body}</div>}
      {excerpt && <button type="button" className="link-button" aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}>{expanded ? '收起说明' : '展开完整说明'}</button>}</>
      : <p className="block-note">作者未填写发布说明。</p>}
  </div>;
}
