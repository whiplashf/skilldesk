import { useState } from 'react';
import type { GitHubRelease } from '../api/types';
import { formatDateTime } from '../lib/format';

export function ReleaseNotes({ release }: { release: GitHubRelease }) {
  const [expanded, setExpanded] = useState(false);
  const excerpt = release.body.split('\n').slice(0, 5).join('\n').slice(0, 380).trimEnd();
  const long = excerpt.length < release.body.length;
  const published = Date.parse(release.publishedAt);
  return <div className="release-notes">
    <div className="release-notes-heading"><strong>发布说明</strong>
      {Number.isFinite(published) && <time dateTime={release.publishedAt}>{formatDateTime(published / 1000).slice(0, 10)}</time>}
      <a href={release.url} target="_blank" rel="noreferrer">GitHub 原文 ↗</a>
    </div>
    {release.title && release.title !== release.tag && <p className="release-title">{release.title}</p>}
    {release.body ? <><div className="release-body">{expanded || !long ? release.body : excerpt + '…'}</div>
      {long && <button type="button" className="link-button" aria-expanded={expanded}
        onClick={() => setExpanded(!expanded)}>{expanded ? '收起说明' : '展开完整说明'}</button>}</>
      : <p className="block-note">作者未填写发布说明。</p>}
  </div>;
}
